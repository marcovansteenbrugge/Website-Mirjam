"""FastAPI-applicatie voor Nissan Ariya Connect.

Implementeert exact de endpoints uit `CONTRACT.md` en serveert daarnaast de
statische frontend uit `../web` op `/`.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import require_token
from .config import Settings, get_settings
from .errors import ApiError, ErrorResponse
from .jobs import JobStore, RefreshRateLimiter
from .redaction import Redactor, install_redaction
from .vehicle.base import (
    MAX_TARGET_TEMP_C,
    MIN_TARGET_TEMP_C,
    TARGET_TEMP_STEP_C,
    BatteryState,
    Capabilities,
    ClimateState,
    LocationState,
    OdometerState,
    TyreState,
    VehicleClient,
    VehicleInfo,
)
from .vehicle.mock import MockVehicleClient

_LOGGER = logging.getLogger("nissan_connect")

#: Map met de statische frontend. Een andere ontwikkelaar vult deze; hij mag
#: dus (nog) ontbreken zonder dat de backend stukloopt.
WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"

#: Alle foutresponses van de API volgen het contract-schema.
_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    "4XX": {"model": ErrorResponse, "description": "Fout volgens het contract-foutschema"},
    "5XX": {"model": ErrorResponse, "description": "Fout volgens het contract-foutschema"},
}


# --------------------------------------------------------------------------- #
# Request- en responsmodellen
# --------------------------------------------------------------------------- #


class ClimateStartRequest(BaseModel):
    """Body van `POST /api/climate/start`."""

    model_config = ConfigDict(extra="ignore")

    target_temp_c: float


class JobCreated(BaseModel):
    """Antwoord op een commando dat een job start (contract)."""

    job_id: str
    status: str


class JobState(BaseModel):
    """Antwoord van `GET /api/jobs/{job_id}` (contract)."""

    job_id: str
    status: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# Hulpfuncties
# --------------------------------------------------------------------------- #


def build_vehicle_client(settings: Settings, redactor: Redactor) -> VehicleClient:
    """Kies de juiste auto-client op basis van de instellingen."""
    if settings.mock:
        _LOGGER.info("MOCK=1 — er wordt géén verbinding met Nissan gemaakt.")
        return MockVehicleClient(failure_rate=settings.mock_failure_rate)

    if not settings.credentials_present:
        raise RuntimeError(
            "NISSAN_USERNAME en/of NISSAN_PASSWORD ontbreken. Zet MOCK=1 om zonder "
            "Nissan-account te draaien, of vul de inloggegevens in."
        )

    # Pas hier importeren: zo hoeft mock-modus niets van Kamereon te weten.
    from .vehicle.kamereon import KamereonVehicleClient

    _LOGGER.info("Echte modus — verbinding met NissanConnect (regio %s).", settings.nissan_region)
    return KamereonVehicleClient(
        username=settings.nissan_username,
        password=settings.nissan_password,
        region=settings.nissan_region,
        redactor=redactor,
    )


def validate_target_temp(value: float) -> float:
    """Controleer het temperatuurbereik en de stapgrootte uit het contract."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ApiError("invalid_request", "Geef een temperatuur in graden op.")
    temp = float(value)
    if temp < MIN_TARGET_TEMP_C or temp > MAX_TARGET_TEMP_C:
        raise ApiError(
            "invalid_request",
            f"Kies een temperatuur tussen {MIN_TARGET_TEMP_C:.0f} en {MAX_TARGET_TEMP_C:.0f} graden.",
        )
    steps = temp / TARGET_TEMP_STEP_C
    if abs(steps - round(steps)) > 1e-6:
        raise ApiError(
            "invalid_request",
            "Kies een hele graad, bijvoorbeeld 21 of 22. De auto kent geen halve graden.",
        )
    return round(round(steps) * TARGET_TEMP_STEP_C, 1)


def _client(request: Request) -> VehicleClient:
    client: VehicleClient | None = getattr(request.app.state, "vehicle_client", None)
    if client is None:  # pragma: no cover - alleen bij verkeerde opstart
        raise ApiError("upstream_error", "De verbinding met de auto is nog niet klaar.")
    return client


def _jobs(request: Request) -> JobStore:
    return request.app.state.jobs


def _settings(request: Request) -> Settings:
    return request.app.state.settings


# --------------------------------------------------------------------------- #
# Job-workers
# --------------------------------------------------------------------------- #


async def _battery_refresh_worker(
    client: VehicleClient, settings: Settings
) -> dict[str, Any]:
    """Vraag een verse meting en wacht tot de auto zich meldt.

    Nissan bevestigt het commando meteen, maar de nieuwe waarde druppelt pas
    later binnen. We pollen de gecachete stand tot `updated_at` opschuift.
    """
    before: BatteryState = await client.get_battery()
    baseline: datetime | None = before.updated_at

    await client.request_battery_refresh()

    while True:
        await asyncio.sleep(settings.job_poll_interval_seconds)
        current = await client.get_battery()
        if current.updated_at is not None and current.updated_at != baseline:
            return current.model_dump(mode="json")


async def _climate_worker(
    client: VehicleClient,
    settings: Settings,
    *,
    start: bool,
    target_temp_c: float | None = None,
) -> dict[str, Any]:
    """Start of stop de klimaatregeling en wacht op de bevestiging van de auto."""
    if start:
        assert target_temp_c is not None
        await client.start_climate(target_temp_c)
    else:
        await client.stop_climate()

    while True:
        await asyncio.sleep(settings.job_poll_interval_seconds)
        state: ClimateState = await client.get_climate()
        if state.running is bool(start):
            return state.model_dump(mode="json")


# --------------------------------------------------------------------------- #
# Applicatie
# --------------------------------------------------------------------------- #


def create_app(
    settings: Settings | None = None,
    *,
    vehicle_client: VehicleClient | None = None,
) -> FastAPI:
    """Bouw de FastAPI-app.

    `settings` en `vehicle_client` kunnen geïnjecteerd worden; dat is wat de
    tests doen. In productie komt alles uit de environment.
    """
    resolved_settings = settings or get_settings()

    redactor = Redactor(
        [resolved_settings.app_token, resolved_settings.nissan_password]
    )
    install_redaction(
        redactor,
        ["nissan_connect", "app.vehicle.kamereon", "app.jobs", "httpx", "uvicorn.error"],
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.vehicle_client = vehicle_client or build_vehicle_client(
            resolved_settings, redactor
        )
        try:
            yield
        finally:
            await application.state.jobs.shutdown()
            if vehicle_client is None:
                await application.state.vehicle_client.aclose()

    app = FastAPI(
        title="Nissan Ariya Connect",
        version="1.0.0",
        description="Persoonlijke backend om de eigen Ariya uit te lezen en voor te verwarmen.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.redactor = redactor
    app.state.jobs = JobStore(ttl_seconds=resolved_settings.job_ttl_seconds)
    app.state.refresh_limiter = RefreshRateLimiter(
        resolved_settings.poll_min_interval_seconds
    )
    if vehicle_client is not None:
        app.state.vehicle_client = vehicle_client

    _register_exception_handlers(app)
    _register_routes(app)
    _mount_frontend(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """Zorg dat *elke* fout het contract-schema volgt."""

    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        detail = "Dat verzoek klopt niet — controleer wat je meestuurt."
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
            if location == "target_temp_c":
                detail = "Geef een temperatuur op, bijvoorbeeld {\"target_temp_c\": 21.0}."
                break
        error_obj = ApiError("invalid_request", detail)
        return JSONResponse(status_code=error_obj.status_code, content=error_obj.to_dict())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Alleen API-paden krijgen het contract-schema; de statische frontend
        # mag gewoon een normale 404-pagina teruggeven.
        if not request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )
        code = "unauthorized" if exc.status_code in (401, 403) else "invalid_request"
        if exc.status_code == 404:
            error_obj = ApiError(
                "invalid_request", "Dit adres bestaat niet.", status_code=404
            )
        elif exc.status_code == 405:
            error_obj = ApiError(
                "invalid_request", "Deze actie is hier niet toegestaan.", status_code=405
            )
        else:
            error_obj = ApiError(code, status_code=exc.status_code)  # type: ignore[arg-type]
        return JSONResponse(status_code=error_obj.status_code, content=error_obj.to_dict())

    @app.exception_handler(NotImplementedError)
    async def _not_implemented(_request: Request, exc: NotImplementedError) -> JSONResponse:
        _LOGGER.error("Niet-geverifieerde functie aangeroepen: %s", exc)
        error_obj = ApiError(
            "upstream_error",
            "Deze functie is nog niet beschikbaar voor jouw auto.",
            retryable=False,
        )
        return JSONResponse(status_code=501, content=error_obj.to_dict())

    @app.middleware("http")
    async def _catch_unexpected(request: Request, call_next: Any) -> Any:
        """Vangnet: ook een onverwachte fout hoort het contract-schema te volgen."""
        try:
            return await call_next(request)
        except ApiError as exc:  # pragma: no cover - normaal al afgevangen
            return JSONResponse(status_code=exc.status_code, content=exc.to_dict())
        except Exception as exc:  # noqa: BLE001
            redactor: Redactor = app.state.redactor
            _LOGGER.error("Onverwachte fout: %s", redactor.scrub(repr(exc)))
            error_obj = ApiError("upstream_error")
            return JSONResponse(
                status_code=error_obj.status_code, content=error_obj.to_dict()
            )


def _register_routes(app: FastAPI) -> None:
    guard = [Depends(require_token)]

    @app.get(
        "/api/vehicle",
        response_model=VehicleInfo,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Statische gegevens van de auto",
    )
    async def get_vehicle(request: Request) -> VehicleInfo:
        return await _client(request).get_vehicle()

    @app.get(
        "/api/battery",
        response_model=BatteryState,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Laatst bekende accustand (raakt de auto niet aan)",
    )
    async def get_battery(request: Request) -> BatteryState:
        return await _client(request).get_battery()

    @app.post(
        "/api/battery/refresh",
        response_model=JobCreated,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Vraag de auto om een verse meting",
    )
    async def refresh_battery(request: Request) -> JobCreated:
        jobs = _jobs(request)
        settings = _settings(request)
        limiter: RefreshRateLimiter = request.app.state.refresh_limiter

        # Loopt er al een meting? Geef dan diezelfde job terug in plaats van de
        # auto nog een keer wakker te maken.
        running = jobs.active_job("battery_refresh")
        if running is not None:
            return JobCreated(job_id=running.id, status=running.status)

        # Pas hierna de rem: de auto wordt zo dadelijk echt wakker gemaakt.
        limiter.check()

        client = _client(request)
        job, started = await jobs.start(
            "battery_refresh",
            lambda: _battery_refresh_worker(client, settings),
            timeout_seconds=settings.job_timeout_seconds,
        )
        if started:
            limiter.mark()
        return JobCreated(job_id=job.id, status=job.status)

    @app.get(
        "/api/jobs/{job_id}",
        response_model=JobState,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Status van een commando",
    )
    async def get_job(request: Request, job_id: str) -> JobState:
        job = _jobs(request).get(job_id)
        if job is None:
            raise ApiError(
                "invalid_request",
                "Deze opdracht is niet (meer) bekend. Vraag hem opnieuw aan.",
                status_code=404,
            )
        return JobState(**job.to_dict())

    @app.get(
        "/api/climate",
        response_model=ClimateState,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Status van de voorverwarming",
    )
    async def get_climate(request: Request) -> ClimateState:
        return await _client(request).get_climate()

    @app.post(
        "/api/climate/start",
        response_model=JobCreated,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Start het voorverwarmen/-koelen",
    )
    async def start_climate(request: Request, body: ClimateStartRequest) -> JobCreated:
        temp = validate_target_temp(body.target_temp_c)
        jobs = _jobs(request)
        settings = _settings(request)
        client = _client(request)

        running = jobs.active_job("climate_start") or jobs.active_job("climate_stop")
        if running is not None:
            return JobCreated(job_id=running.id, status=running.status)

        job, _ = await jobs.start(
            "climate_start",
            lambda: _climate_worker(client, settings, start=True, target_temp_c=temp),
            timeout_seconds=settings.job_timeout_seconds,
        )
        return JobCreated(job_id=job.id, status=job.status)

    @app.post(
        "/api/climate/stop",
        response_model=JobCreated,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Stop het voorverwarmen/-koelen",
    )
    async def stop_climate(request: Request) -> JobCreated:
        jobs = _jobs(request)
        settings = _settings(request)
        client = _client(request)

        running = jobs.active_job("climate_stop")
        if running is not None:
            return JobCreated(job_id=running.id, status=running.status)

        job, _ = await jobs.start(
            "climate_stop",
            lambda: _climate_worker(client, settings, start=False),
            timeout_seconds=settings.job_timeout_seconds,
        )
        return JobCreated(job_id=job.id, status=job.status)


    # ---------------------------------------------------------------- #
    # Gegevens die de auto sinds 14-09-2026 aantoonbaar teruggeeft
    #
    # Alle drie zijn *gecachete* waarden uit de Nissan-cloud: ze maken de auto
    # niet wakker en vallen dus niet onder de rem op `battery/refresh`.
    # Ondersteunt deze auto een onderdeel niet, dan geeft de client een
    # FeatureUnavailable -- een ApiError met een Nederlandse uitleg, die door
    # de bestaande foutafhandeling gewoon het contract-schema volgt.
    # ---------------------------------------------------------------- #

    @app.get(
        "/api/location",
        response_model=LocationState,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Waar de auto het laatst gezien is",
    )
    async def get_location(request: Request) -> LocationState:
        return await _client(request).get_location()

    @app.get(
        "/api/odometer",
        response_model=OdometerState,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Kilometerstand",
    )
    async def get_odometer(request: Request) -> OdometerState:
        return await _client(request).get_odometer()

    @app.get(
        "/api/tyres",
        response_model=TyreState,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Bandenspanning van alle vier de wielen",
    )
    async def get_tyres(request: Request) -> TyreState:
        return await _client(request).get_tyres()

    @app.get(
        "/api/capabilities",
        response_model=Capabilities,
        dependencies=guard,
        responses=_ERROR_RESPONSES,
        summary="Wat deze auto werkelijk ondersteunt",
    )
    async def get_capabilities(request: Request) -> Capabilities:
        """Wordt door de client gemeten en onthouden; dit is dus goedkoop."""
        return await _client(request).get_capabilities()


def _mount_frontend(app: FastAPI) -> None:
    """Serveer de statische PWA op `/`, als die er al is.

    De frontend wordt door iemand anders gebouwd. Ontbreekt de map, dan draait
    de API gewoon door -- we maken hier zelf géén bestanden aan.
    """
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
        _LOGGER.info("Frontend geserveerd vanuit %s", WEB_DIR)
    else:
        _LOGGER.warning(
            "Map %s bestaat nog niet — alleen de API is beschikbaar op /api/*.", WEB_DIR
        )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


_configure_logging()


_app_singleton: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """Maak `uvicorn app.main:app` mogelijk zonder de app bij import te bouwen.

    Zo kan dit bestand geïmporteerd worden (bijvoorbeeld door de tests) zonder
    meteen de environment-configuratie af te dwingen, terwijl `app.main:app`
    voor uvicorn gewoon werkt.
    """
    if name == "app":
        global _app_singleton
        if _app_singleton is None:
            _app_singleton = create_app()
        return _app_singleton
    raise AttributeError(f"module {__name__!r} heeft geen attribuut {name!r}")
