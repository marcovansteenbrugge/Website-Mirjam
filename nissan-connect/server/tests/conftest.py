"""Gedeelde fixtures. Alle tests draaien tegen de mock-auto."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator, Callable

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.vehicle.mock import MockVehicleClient  # noqa: E402

TEST_TOKEN = "test-token-dat-lang-genoeg-is"


class FakeClock:
    """Bestuurbare klok, zodat tests niet hoeven te wachten."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 13, 8, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def settings() -> Settings:
    """Instellingen voor tests: mock-modus, snelle jobs, geen rate limit."""
    return Settings(
        app_token=TEST_TOKEN,
        mock=True,
        poll_min_interval_seconds=0,
        job_poll_interval_seconds=0.01,
        job_timeout_seconds=3.0,
        job_ttl_seconds=600.0,
        mock_failure_rate=0.0,
    )


@pytest.fixture
def vehicle(clock: FakeClock) -> MockVehicleClient:
    """Een voorspelbare mock-auto (nooit spontaan in slaapstand)."""
    return MockVehicleClient(
        failure_rate=0.0,
        seed=1234,
        climate_spool_seconds=0.0,
        refresh_delay_seconds=0.0,
        now_factory=clock,
    )


@pytest_asyncio.fixture
async def client(
    settings: Settings, vehicle: MockVehicleClient
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-client tegen de app, mét geldig token."""
    app = create_app(settings, vehicle_client=vehicle)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as http_client:
        http_client.app = app  # type: ignore[attr-defined]
        async with app.router.lifespan_context(app):
            yield http_client


@pytest_asyncio.fixture
async def anon_client(
    settings: Settings, vehicle: MockVehicleClient
) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP-client zonder token."""
    app = create_app(settings, vehicle_client=vehicle)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        c.app = app  # type: ignore[attr-defined]
        async with app.router.lifespan_context(app):
            yield c


@pytest.fixture
def app_factory() -> Callable[..., object]:
    """Bouw zelf een app met afwijkende instellingen."""

    def _factory(**overrides: object):
        base = dict(
            app_token=TEST_TOKEN,
            mock=True,
            poll_min_interval_seconds=0,
            job_poll_interval_seconds=0.01,
            job_timeout_seconds=3.0,
            mock_failure_rate=0.0,
        )
        base.update(overrides)
        return Settings(**base)  # type: ignore[arg-type]

    return _factory
