"""Tests tegen de mock-auto: auth, alle endpoints, jobs, rate limit, foutschema."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.config import MIN_APP_TOKEN_LENGTH, Settings
from app.errors import ERROR_CATALOG
from app.jobs import JobStore, RefreshRateLimiter
from app.main import create_app, validate_target_temp
from app.vehicle.mock import MockVehicleClient

from .conftest import TEST_TOKEN, FakeClock

VALID_CODES = set(ERROR_CATALOG)


# --------------------------------------------------------------------------- #
# Hulpfuncties
# --------------------------------------------------------------------------- #


def assert_contract_error(response: httpx.Response, code: str | None = None) -> dict[str, Any]:
    """Controleer dat een foutrespons exact het contract-schema volgt."""
    assert response.status_code >= 400
    body = response.json()
    assert set(body) == {"error"}, f"onverwachte sleutels: {set(body)}"
    error = body["error"]
    assert set(error) == {"code", "message", "retryable"}, f"onverwachte velden: {set(error)}"
    assert error["code"] in VALID_CODES
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["retryable"], bool)
    if code is not None:
        assert error["code"] == code
    return error


async def poll_job(client: httpx.AsyncClient, job_id: str, tries: int = 200) -> dict[str, Any]:
    """Pol een job tot hij klaar is (of geef de laatste stand terug)."""
    body: dict[str, Any] = {}
    for _ in range(tries):
        response = await client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] != "pending":
            return body
        await asyncio.sleep(0.01)
    return body


# --------------------------------------------------------------------------- #
# Configuratie / opstartweigering
# --------------------------------------------------------------------------- #


def test_leeg_app_token_wordt_geweigerd() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(app_token="", mock=True)
    assert "APP_TOKEN" in str(exc.value)


def test_kort_app_token_wordt_geweigerd() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(app_token="x" * (MIN_APP_TOKEN_LENGTH - 1), mock=True)
    assert "te kort" in str(exc.value)


def test_app_token_van_precies_de_minimumlengte_mag() -> None:
    assert Settings(app_token="y" * MIN_APP_TOKEN_LENGTH, mock=True).app_token


# --------------------------------------------------------------------------- #
# Authenticatie
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path,method",
    [
        ("/api/vehicle", "GET"),
        ("/api/battery", "GET"),
        ("/api/battery/refresh", "POST"),
        ("/api/jobs/onbekend", "GET"),
        ("/api/climate", "GET"),
        ("/api/climate/start", "POST"),
        ("/api/climate/stop", "POST"),
    ],
)
async def test_zonder_token_geen_toegang(
    anon_client: httpx.AsyncClient, path: str, method: str
) -> None:
    response = await anon_client.request(method, path, json={"target_temp_c": 21.0})
    assert response.status_code == 401
    assert_contract_error(response, "unauthorized")


async def test_verkeerd_token_geeft_401(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.get(
        "/api/vehicle", headers={"Authorization": "Bearer fout-token-maar-lang-genoeg"}
    )
    assert_contract_error(response, "unauthorized")


async def test_verkeerd_schema_geeft_401(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.get(
        "/api/vehicle", headers={"Authorization": f"Basic {TEST_TOKEN}"}
    )
    assert_contract_error(response, "unauthorized")


async def test_token_met_zelfde_prefix_wordt_afgewezen(anon_client: httpx.AsyncClient) -> None:
    response = await anon_client.get(
        "/api/vehicle", headers={"Authorization": f"Bearer {TEST_TOKEN[:-1]}"}
    )
    assert_contract_error(response, "unauthorized")


# --------------------------------------------------------------------------- #
# GET /api/vehicle
# --------------------------------------------------------------------------- #


async def test_vehicle_endpoint(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/vehicle")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"vin", "nickname", "model", "battery_capacity_kwh"}
    assert body["vin"].startswith("SJN")
    assert body["battery_capacity_kwh"] == 87.0


# --------------------------------------------------------------------------- #
# GET /api/battery
# --------------------------------------------------------------------------- #


async def test_battery_endpoint_velden(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/battery")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "soc_percent",
        "range_km",
        "charging",
        "plugged_in",
        "battery_capacity_kwh",
        "state_of_health_percent",
        "updated_at",
        "stale_minutes",
    }
    assert 0 <= body["soc_percent"] <= 100
    assert body["charging"] is False
    assert body["plugged_in"] is True
    assert body["updated_at"].endswith("Z")
    assert body["stale_minutes"] == 42


async def test_soc_zakt_bij_stilstand_en_stijgt_bij_laden(
    client: httpx.AsyncClient, vehicle: MockVehicleClient, clock: FakeClock
) -> None:
    start = (await client.get("/api/battery")).json()["soc_percent"]

    clock.advance(10 * 3600)  # tien uur stilstand
    leeger = (await client.get("/api/battery")).json()["soc_percent"]
    assert leeger < start

    vehicle.set_charging(True)
    clock.advance(2 * 3600)
    voller = (await client.get("/api/battery")).json()["soc_percent"]
    assert voller > leeger
    assert (await client.get("/api/battery")).json()["charging"] is True


async def test_stale_minutes_loopt_op(client: httpx.AsyncClient, clock: FakeClock) -> None:
    eerst = (await client.get("/api/battery")).json()["stale_minutes"]
    clock.advance(30 * 60)
    later = (await client.get("/api/battery")).json()["stale_minutes"]
    assert later == eerst + 30


# --------------------------------------------------------------------------- #
# POST /api/battery/refresh + joblevenscyclus
# --------------------------------------------------------------------------- #


async def test_refresh_levert_job_op_die_slaagt(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/battery/refresh")
    assert response.status_code == 200
    created = response.json()
    assert set(created) == {"job_id", "status"}
    assert created["status"] == "pending"

    job = await poll_job(client, created["job_id"])

    assert job["status"] == "success"
    assert set(job) == {"job_id", "status", "result", "error"}
    assert job["error"] is None
    assert 0 <= job["result"]["soc_percent"] <= 100
    assert job["result"]["stale_minutes"] == 0


async def test_onbekende_job_geeft_contractfout(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/jobs/bestaat-niet")
    assert response.status_code == 404
    assert_contract_error(response, "invalid_request")


async def test_tweede_refresh_tijdens_lopende_job_hergebruikt_de_job(
    client: httpx.AsyncClient,
) -> None:
    eerste = (await client.post("/api/battery/refresh")).json()
    tweede = (await client.post("/api/battery/refresh")).json()
    assert eerste["job_id"] == tweede["job_id"]
    assert tweede["status"] == "pending"


async def test_job_die_niet_op_tijd_antwoordt_krijgt_status_timeout(
    settings: Settings, clock: FakeClock
) -> None:
    slaperig = MockVehicleClient(
        failure_rate=0.0,
        seed=7,
        # De auto meldt zich pas over een uur -- veel later dan de job-timeout.
        refresh_delay_seconds=3600.0,
        climate_spool_seconds=0.0,
        now_factory=clock,
    )
    snel = settings.model_copy(update={"job_timeout_seconds": 0.2})
    app = create_app(snel, vehicle_client=slaperig)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as http_client:
        async with app.router.lifespan_context(app):
            created = (await http_client.post("/api/battery/refresh")).json()
            job = await poll_job(http_client, created["job_id"])
            assert job["status"] == "timeout"
            assert job["error"]["code"] == "vehicle_asleep"
            assert job["error"]["retryable"] is True


async def test_slapende_auto_laat_de_job_falen(settings: Settings, clock: FakeClock) -> None:
    slapend = MockVehicleClient(
        failure_rate=0.0, seed=3, climate_spool_seconds=0.0, now_factory=clock
    )
    slapend.force_asleep = True
    app = create_app(settings, vehicle_client=slapend)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as http_client:
        async with app.router.lifespan_context(app):
            created = (await http_client.post("/api/battery/refresh")).json()
            job = await poll_job(http_client, created["job_id"])
            assert job["status"] == "failed"
            assert job["error"]["code"] == "vehicle_asleep"
            assert job["error"]["message"]
            assert job["error"]["retryable"] is True


# --------------------------------------------------------------------------- #
# Rate limit op geforceerde metingen
# --------------------------------------------------------------------------- #


async def test_rate_limit_blokkeert_snelle_tweede_meting(
    settings: Settings, clock: FakeClock
) -> None:
    auto = MockVehicleClient(
        failure_rate=0.0,
        seed=5,
        refresh_delay_seconds=0.0,
        climate_spool_seconds=0.0,
        now_factory=clock,
    )
    beschermd = settings.model_copy(update={"poll_min_interval_seconds": 900})
    app = create_app(beschermd, vehicle_client=auto)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as http_client:
        async with app.router.lifespan_context(app):
            eerste = (await http_client.post("/api/battery/refresh")).json()
            clock.advance(30)
            await poll_job(http_client, eerste["job_id"])

            geweigerd = await http_client.post("/api/battery/refresh")
            assert geweigerd.status_code == 429
            fout = assert_contract_error(geweigerd, "rate_limited")
            assert fout["retryable"] is True
            assert "12V" in fout["message"]

            # De gewone (gecachete) uitlezing blijft gewoon werken.
            assert (await http_client.get("/api/battery")).status_code == 200


def test_rate_limiter_zonder_interval_laat_alles_door() -> None:
    limiter = RefreshRateLimiter(0)
    limiter.mark()
    limiter.check()  # mag niet opgooien


def test_rate_limiter_telt_af() -> None:
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)
    limiter = RefreshRateLimiter(900)
    limiter.mark(start)
    assert limiter.seconds_remaining(start) == pytest.approx(900)
    assert limiter.seconds_remaining(start + timedelta(seconds=600)) == pytest.approx(300)
    assert limiter.seconds_remaining(start + timedelta(seconds=900)) == 0


# --------------------------------------------------------------------------- #
# Klimaatregeling
# --------------------------------------------------------------------------- #


async def test_climate_status(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/climate")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"running", "target_temp_c", "updated_at"}
    assert body["running"] is False


async def test_climate_start_en_stop(client: httpx.AsyncClient) -> None:
    created = (await client.post("/api/climate/start", json={"target_temp_c": 21.0})).json()
    assert set(created) == {"job_id", "status"}
    job = await poll_job(client, created["job_id"])
    assert job["status"] == "success", job
    assert job["result"]["running"] is True
    assert job["result"]["target_temp_c"] == 21.0

    status = (await client.get("/api/climate")).json()
    assert status["running"] is True
    assert status["target_temp_c"] == 21.0

    gestopt = (await client.post("/api/climate/stop")).json()
    job = await poll_job(client, gestopt["job_id"])
    assert job["status"] == "success", job
    assert job["result"]["running"] is False
    assert (await client.get("/api/climate")).json()["running"] is False


async def test_climate_duurt_even_voordat_hij_draait(
    settings: Settings, clock: FakeClock
) -> None:
    traag = MockVehicleClient(
        failure_rate=0.0, seed=9, climate_spool_seconds=20.0, now_factory=clock
    )
    app = create_app(settings, vehicle_client=traag)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as http_client:
        async with app.router.lifespan_context(app):
            await http_client.post("/api/climate/start", json={"target_temp_c": 20.0})
            # Nog geen 20 seconden verstreken: de auto meldt nog niets.
            assert (await http_client.get("/api/climate")).json()["running"] is False
            clock.advance(21)
            assert (await http_client.get("/api/climate")).json()["running"] is True


@pytest.mark.parametrize("temp", [15.5, 26.5, 0, 100, -5])
async def test_temperatuur_buiten_bereik(client: httpx.AsyncClient, temp: float) -> None:
    response = await client.post("/api/climate/start", json={"target_temp_c": temp})
    fout = assert_contract_error(response, "invalid_request")
    assert response.status_code == 400
    assert fout["retryable"] is False


@pytest.mark.parametrize("temp", [21.5, 21.3, 19.25, 16.1])
async def test_alleen_hele_graden(client: httpx.AsyncClient, temp: float) -> None:
    """De auto kent geen halve graden -- zie de afwijking op CONTRACT.md in base.py."""
    response = await client.post("/api/climate/start", json={"target_temp_c": temp})
    fout = assert_contract_error(response, "invalid_request")
    assert "hele graad" in fout["message"]


@pytest.mark.parametrize("temp", [16.0, 17.0, 21.0, 22.0, 26.0])
def test_geldige_temperaturen(temp: float) -> None:
    assert validate_target_temp(temp) == temp


async def test_climate_start_zonder_body(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/climate/start")
    assert_contract_error(response, "invalid_request")


async def test_climate_start_met_onzin_body(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/climate/start", json={"target_temp_c": "warm"})
    assert_contract_error(response, "invalid_request")


# --------------------------------------------------------------------------- #
# Jobstore afzonderlijk
# --------------------------------------------------------------------------- #


async def test_jobstore_verwijdert_verlopen_jobs() -> None:
    from datetime import timedelta

    store = JobStore(ttl_seconds=600)

    async def werk() -> dict[str, Any]:
        return {"klaar": True}

    job, gestart = await store.start("battery_refresh", werk, timeout_seconds=2)
    assert gestart is True
    await asyncio.sleep(0.05)
    assert store.get(job.id) is not None
    assert store.get(job.id).status == "success"  # type: ignore[union-attr]

    # Doe alsof de job elf minuten oud is.
    job.created_at -= timedelta(seconds=660)
    assert store.get(job.id) is None


async def test_jobstore_start_geen_tweede_job_van_hetzelfde_soort() -> None:
    store = JobStore(ttl_seconds=600)
    losgelaten = asyncio.Event()

    async def traag() -> dict[str, Any]:
        await losgelaten.wait()
        return {}

    eerste, gestart1 = await store.start("battery_refresh", traag, timeout_seconds=5)
    tweede, gestart2 = await store.start("battery_refresh", traag, timeout_seconds=5)
    assert gestart1 is True
    assert gestart2 is False
    assert eerste.id == tweede.id
    losgelaten.set()
    await asyncio.sleep(0.05)
    await store.shutdown()


async def test_jobstore_vangt_onbekende_fouten_af() -> None:
    store = JobStore(ttl_seconds=600)

    async def stukje() -> dict[str, Any]:
        raise RuntimeError("iets onverwachts met geheim wachtwoord")

    job, _ = await store.start("climate_start", stukje, timeout_seconds=2)
    await asyncio.sleep(0.05)
    bijgewerkt = store.get(job.id)
    assert bijgewerkt is not None
    assert bijgewerkt.status == "failed"
    assert bijgewerkt.error is not None
    assert bijgewerkt.error["code"] == "upstream_error"
    # De ruwe foutmelding lekt niet naar de gebruiker.
    assert "wachtwoord" not in bijgewerkt.error["message"]


# --------------------------------------------------------------------------- #
# Foutschema breed
# --------------------------------------------------------------------------- #


async def test_onbekend_api_pad_volgt_het_foutschema(client: httpx.AsyncClient) -> None:
    assert_contract_error(await client.get("/api/bestaat-niet"), "invalid_request")


async def test_verkeerde_methode_volgt_het_foutschema(client: httpx.AsyncClient) -> None:
    assert_contract_error(await client.get("/api/climate/start"), "invalid_request")


def test_alle_contractcodes_hebben_een_nederlandse_tekst() -> None:
    verwacht = {
        "unauthorized",
        "nissan_auth_failed",
        "vehicle_asleep",
        "rate_limited",
        "not_plugged_in",
        "upstream_error",
        "invalid_request",
    }
    assert set(ERROR_CATALOG) == verwacht
    for code, (status, bericht, retryable) in ERROR_CATALOG.items():
        assert status >= 400, code
        assert bericht.strip(), code
        assert isinstance(retryable, bool), code


# --------------------------------------------------------------------------- #
# Statische frontend
# --------------------------------------------------------------------------- #


async def test_app_start_ook_zonder_frontendmap(
    settings: Settings, vehicle: MockVehicleClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """De frontend wordt door iemand anders gebouwd; zolang die map er niet is
    moet de API gewoon blijven werken."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "WEB_DIR", tmp_path / "bestaat-niet")
    app = create_app(settings, vehicle_client=vehicle)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"},
    ) as http_client:
        async with app.router.lifespan_context(app):
            assert (await http_client.get("/api/vehicle")).status_code == 200


async def test_frontendmap_wordt_geserveerd(
    settings: Settings, vehicle: MockVehicleClient, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import app.main as main_module

    (tmp_path / "index.html").write_text("<h1>Ariya</h1>", encoding="utf-8")
    monkeypatch.setattr(main_module, "WEB_DIR", tmp_path)
    app = create_app(settings, vehicle_client=vehicle)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        async with app.router.lifespan_context(app):
            response = await c.get("/")
            assert response.status_code == 200
            assert "Ariya" in response.text
