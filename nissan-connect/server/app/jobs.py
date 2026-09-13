"""In-memory jobstore voor langlopende commando's.

`POST /api/battery/refresh`, `/api/climate/start` en `/api/climate/stop` kunnen
10-60 seconden duren. Die draaien daarom als achtergrondtaak; de frontend pollt
`GET /api/jobs/{job_id}`.

Bewust simpel: één eigenaar, één auto, één proces. Jobs leven in het geheugen en
verdwijnen na 10 minuten. Bij een herstart is alles weg -- dat is prima, want een
job die niemand meer pollt is toch waardeloos.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Literal

from .errors import ApiError
from .vehicle.base import utcnow

_LOGGER = logging.getLogger(__name__)

JobStatus = Literal["pending", "success", "failed", "timeout"]

#: Soorten jobs. Per soort mag er maar één tegelijk lopen.
JobKind = Literal["battery_refresh", "climate_start", "climate_stop"]

DEFAULT_TTL_SECONDS = 600.0  # 10 minuten, zoals afgesproken


@dataclass
class Job:
    """Eén achtergrondcommando."""

    id: str
    kind: str
    status: JobStatus = "pending"
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialiseer volgens het contract van `GET /api/jobs/{job_id}`."""
        return {
            "job_id": self.id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }

    @property
    def is_running(self) -> bool:
        return self.status == "pending"


class JobStore:
    """Houdt lopende en recent afgeronde jobs bij."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._jobs: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    # -- opvragen -------------------------------------------------------------

    def get(self, job_id: str) -> Job | None:
        """Geef een job terug, of `None` als die niet (meer) bestaat."""
        self._purge_expired()
        return self._jobs.get(job_id)

    def active_job(self, kind: JobKind) -> Job | None:
        """Geef de lopende job van dit soort, als die er is."""
        for job in self._jobs.values():
            if job.kind == kind and job.is_running:
                return job
        return None

    # -- starten --------------------------------------------------------------

    async def start(
        self,
        kind: JobKind,
        worker: Callable[[], Awaitable[dict[str, Any] | None]],
        *,
        timeout_seconds: float,
    ) -> tuple[Job, bool]:
        """Start een job van dit soort.

        Geeft `(job, nieuw_gestart)` terug. Loopt er al een job van dit soort,
        dan wordt die bestaande job teruggegeven en gebeurt er niets nieuws --
        zo wordt er nooit een tweede commando naar de auto gestuurd terwijl het
        eerste nog onderweg is.
        """
        async with self._lock:
            self._purge_expired()
            running = self.active_job(kind)
            if running is not None:
                return running, False

            job = Job(id=secrets.token_urlsafe(9), kind=kind)
            self._jobs[job.id] = job
            task = asyncio.create_task(self._run(job, worker, timeout_seconds))
            self._tasks[job.id] = task
            task.add_done_callback(lambda _t, jid=job.id: self._tasks.pop(jid, None))
            return job, True

    async def _run(
        self,
        job: Job,
        worker: Callable[[], Awaitable[dict[str, Any] | None]],
        timeout_seconds: float,
    ) -> None:
        try:
            result = await asyncio.wait_for(worker(), timeout=timeout_seconds)
            job.result = result
            job.status = "success"
        except asyncio.TimeoutError:
            job.status = "timeout"
            job.error = ApiError(
                "vehicle_asleep",
                "De auto heeft niet op tijd geantwoord. Hij slaapt waarschijnlijk; "
                "probeer het over een paar minuten nog eens.",
            ).to_dict()["error"]
        except asyncio.CancelledError:  # pragma: no cover - alleen bij afsluiten
            job.status = "failed"
            job.error = ApiError(
                "upstream_error", "Het commando is afgebroken."
            ).to_dict()["error"]
            raise
        except ApiError as exc:
            job.status = "failed"
            job.error = exc.to_dict()["error"]
        except Exception:  # noqa: BLE001 - onbekende fout mag de app niet slopen
            _LOGGER.exception("Job %s (%s) is onverwacht gestrand", job.id, job.kind)
            job.status = "failed"
            job.error = ApiError("upstream_error").to_dict()["error"]
        finally:
            job.finished_at = utcnow()

    # -- opruimen -------------------------------------------------------------

    def _purge_expired(self) -> None:
        """Gooi jobs weg die ouder zijn dan de TTL."""
        cutoff = utcnow() - self._ttl
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if not job.is_running and job.created_at < cutoff
        ]
        for job_id in expired:
            self._jobs.pop(job_id, None)

    async def shutdown(self) -> None:
        """Breek nog lopende taken netjes af."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: B014
                pass
        self._tasks.clear()


class RefreshRateLimiter:
    """Minimale tussentijd tussen geforceerde metingen.

    Dit is géén luxe: een elektrische auto die slaapt wordt door elke geforceerde
    meting wakker gemaakt. Te vaak pollen trekt de 12V-startaccu leeg, en met een
    lege 12V-accu doet de hele auto niets meer -- ook de laadklep niet. Vandaar
    standaard minimaal 15 minuten tussen twee verse metingen.

    De reguliere `GET /api/battery` valt hier *niet* onder: die leest alleen wat
    Nissan al in de cloud heeft staan en raakt de auto niet aan.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = float(min_interval_seconds)
        self._last_request: datetime | None = None

    @property
    def min_interval_seconds(self) -> float:
        return self._min_interval

    def seconds_remaining(self, now: datetime | None = None) -> float:
        """Hoeveel seconden moet er nog gewacht worden? 0 als het mag."""
        if self._last_request is None or self._min_interval <= 0:
            return 0.0
        elapsed = ((now or utcnow()) - self._last_request).total_seconds()
        return max(0.0, self._min_interval - elapsed)

    def check(self, now: datetime | None = None) -> None:
        """Gooi `ApiError('rate_limited')` als het nog te vroeg is."""
        remaining = self.seconds_remaining(now)
        if remaining <= 0:
            return
        minutes = int(remaining // 60)
        seconds = int(remaining % 60)
        wait = f"{minutes} min {seconds} sec" if minutes else f"{seconds} seconden"
        raise ApiError(
            "rate_limited",
            "De auto is net al wakker gemaakt voor een meting. Om de 12V-accu te "
            f"sparen kan dat pas over {wait} weer. De getoonde waarden blijven "
            "gewoon werken.",
        )

    def mark(self, now: datetime | None = None) -> None:
        """Leg vast dat er zojuist een verse meting is aangevraagd."""
        self._last_request = now or utcnow()

    def reset(self) -> None:
        """Alleen voor tests."""
        self._last_request = None
