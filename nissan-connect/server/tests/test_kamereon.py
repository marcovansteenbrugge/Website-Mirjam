"""Tests voor de echte Kamereon-client die géén Nissan-account nodig hebben.

Alles wat werkelijk netwerkverkeer vereist, kan hier niet getest worden; die
punten staan benoemd in de README en in de docstring van `kamereon.py`.
"""

from __future__ import annotations

import pytest

from app.errors import ApiError
from app.vehicle.kamereon import (
    EU_SETTINGS,
    KamereonVehicleClient,
    _LoginFormParser,
    settings_for_region,
)


def test_nederland_gebruikt_de_eu_backend() -> None:
    assert settings_for_region("NL") is EU_SETTINGS
    assert settings_for_region("nl") is EU_SETTINGS


@pytest.mark.parametrize("regio", ["US", "JP", "AU", "onzin"])
def test_onbekende_regio_wordt_niet_verzonnen(regio: str) -> None:
    with pytest.raises(NotImplementedError) as exc:
        settings_for_region(regio)
    assert "ONGEVERIFIEERD" in str(exc.value)


def test_zonder_inloggegevens_geen_client() -> None:
    with pytest.raises(ApiError) as exc:
        KamereonVehicleClient(username="", password="")
    assert exc.value.code == "nissan_auth_failed"


async def test_halve_graden_zijn_niet_geverifieerd() -> None:
    client = KamereonVehicleClient(username="a@b.nl", password="geheim123")
    try:
        with pytest.raises(NotImplementedError) as exc:
            await client.start_climate(21.5)
        assert "ONGEVERIFIEERD" in str(exc.value)
    finally:
        await client.aclose()


def test_pkce_paar_is_geldig() -> None:
    verifier, challenge = KamereonVehicleClient._pkce_pair()
    assert 43 <= len(verifier) <= 128
    assert "=" not in challenge


def test_inlogformulier_wordt_herkend() -> None:
    html = """
    <html><body>
      <form action="/commonauth" method="post">
        <input name="sessionDataKey" value="abc123"/>
        <input name="regionCode" value="NL"/>
        <input name="username" value=""/>
        <input name="password" value=""/>
      </form>
    </body></html>
    """
    parser = _LoginFormParser()
    parser.feed(html)
    form = parser.login_form
    assert form is not None
    assert form["action"] == "/commonauth"
    assert form["inputs"]["sessionDataKey"] == "abc123"
    assert form["inputs"]["regionCode"] == "NL"


def test_formulier_zonder_wachtwoordveld_wordt_genegeerd() -> None:
    parser = _LoginFormParser()
    parser.feed('<form action="/zoek"><input name="q" value=""/></form>')
    assert parser.login_form is None


def test_statusvertaling_volgt_het_contract() -> None:
    vertaal = KamereonVehicleClient._classify_status
    assert vertaal(200) is None
    assert vertaal(401).code == "nissan_auth_failed"  # type: ignore[union-attr]
    assert vertaal(429).code == "rate_limited"  # type: ignore[union-attr]
    assert vertaal(503).code == "vehicle_asleep"  # type: ignore[union-attr]
    assert vertaal(418).code == "upstream_error"  # type: ignore[union-attr]


def test_wachtwoord_zit_in_de_redactie() -> None:
    client = KamereonVehicleClient(username="a@b.nl", password="zeer-geheim-wachtwoord")
    assert "zeer-geheim-wachtwoord" not in client._scrub(
        "mislukt met zeer-geheim-wachtwoord"
    )


# --------------------------------------------------------------------------- #
# Abonnementscontrole -- de stille killer uit het onderzoeksrapport (sectie 6)
# --------------------------------------------------------------------------- #


def _client() -> KamereonVehicleClient:
    return KamereonVehicleClient(username="a@b.nl", password="geheim123")


def test_actieve_diensten_worden_herkend() -> None:
    auto = {
        "services": [
            {"id": 319, "activationState": "ACTIVATED"},
            {"id": 366, "activationState": "DEACTIVATED"},
        ]
    }
    assert KamereonVehicleClient._active_features(auto) == {"319"}


async def test_verlopen_abonnement_geeft_een_begrijpelijke_melding() -> None:
    client = _client()
    try:
        auto = {"services": [{"id": 319, "activationState": "DEACTIVATED"}]}
        with pytest.raises(ApiError) as exc:
            client._require_feature(auto, "319", "Het uitlezen van de accu")
        assert exc.value.code == "upstream_error"
        assert "abonnement" in exc.value.message
        assert exc.value.retryable is False
    finally:
        await client.aclose()


async def test_ontbrekende_dienst_noemt_de_functie() -> None:
    client = _client()
    try:
        auto = {"services": [{"id": 319, "activationState": "ACTIVATED"}]}
        client._require_feature(auto, "319", "Het uitlezen van de accu")  # mag
        with pytest.raises(ApiError) as exc:
            client._require_feature(auto, "366", "Voorverwarmen")
        assert "Voorverwarmen" in exc.value.message
    finally:
        await client.aclose()


# --------------------------------------------------------------------------- #
# Foutafhandeling
# --------------------------------------------------------------------------- #


def test_fouten_in_een_http_200_worden_herkend() -> None:
    """Kamereon stopt fouten in de body van een 200 -- sectie 6, punt 7."""
    vertaal = KamereonVehicleClient._translate_api_errors
    assert vertaal([{"detail": "vehicle is asleep"}]).code == "vehicle_asleep"
    assert vertaal([{"detail": "car not plugged in"}]).code == "not_plugged_in"
    assert vertaal([{"detail": "iets onbekends"}]).code == "upstream_error"


async def test_afgewezen_inloggegevens_worden_niet_herhaald() -> None:
    """WSO2 kent account-lockout; één afwijzing moet definitief zijn."""
    client = _client()
    try:
        client._auth_blocked = ApiError("nissan_auth_failed")
        with pytest.raises(ApiError) as exc:
            await client._ensure_token()
        assert exc.value.code == "nissan_auth_failed"
    finally:
        await client.aclose()


def test_timeout_is_ruim_genoeg_voor_een_trage_api() -> None:
    """evcc gebruikt 120 s; een krappe timeout lijkt op een kapotte auto."""
    from app.vehicle.kamereon import _HTTP_TIMEOUT

    assert _HTTP_TIMEOUT.read is not None and _HTTP_TIMEOUT.read >= 120.0


def test_ariya_leest_van_de_bff_web_host() -> None:
    """Sectie 3: de Ariya gebruikt v3 op bff-web, niet v1 op de car-adapter."""
    assert EU_SETTINGS["user_base_url"].endswith("/bff-web/")
    assert "caradapter" in EU_SETTINGS["car_adapter_base_url"]


# --------------------------------------------------------------------------- #
# De opgebouwde verzoeken, tegen een nagebootste HTTP-laag
#
# Dit controleert de URL's, de query-parameters en de bodies die we naar Nissan
# zouden sturen -- zonder ook maar één byte het internet op te sturen.
# --------------------------------------------------------------------------- #

import json  # noqa: E402

import httpx  # noqa: E402

_CAR = {
    "vin": "sjnfaaze0u0000001",
    "nickname": "Ariya",
    "modelName": "ARIYA",
    "modelYear": "2024",
    "canGeneration": "cangen2",
    "services": [
        {"id": 319, "activationState": "ACTIVATED"},
        {"id": 366, "activationState": "ACTIVATED"},
        {"id": 2042, "activationState": "ACTIVATED"},
    ],
}


def _make_client(handler) -> KamereonVehicleClient:
    """Client met een vooraf ingevuld token, zodat het inloggen wordt overgeslagen."""
    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    client = KamereonVehicleClient(
        username="a@b.nl", password="geheim123", client=http_client
    )
    client._access_token = "nep-token"
    client._expires_at = float("inf")
    client._user_id = "user-1"
    return client


def _routed(recorder: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        recorder.append(request)
        path = request.url.path
        if path.endswith("/v5/users/user-1/cars"):
            return httpx.Response(200, json={"data": [_CAR]})
        if "/battery-status" in path:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "attributes": {
                            "batteryLevel": 64,
                            "batteryAutonomy": 288,
                            "batteryCapacity": 87,
                            "plugStatus": 1,
                            "chargingStatus": 1,
                            "lastUpdateTime": "2026-09-13T07:32:00Z",
                        }
                    }
                },
            )
        if path.endswith("/hvac-status"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "attributes": {
                            "hvacStatus": "on",
                            "nextTargetTemperature": 21,
                            "lastUpdateTime": "2026-09-13T07:40:00Z",
                        }
                    }
                },
            )
        return httpx.Response(200, json={"data": {"type": "Ok", "id": "actie-1"}})

    return handler


async def test_voertuiggegevens_worden_correct_gelezen() -> None:
    client = _make_client(_routed([]))
    try:
        info = await client.get_vehicle()
        assert info.vin == "SJNFAAZE0U0000001"  # altijd in hoofdletters
        assert info.nickname == "Ariya"
        assert info.model == "ARIYA 2024"
    finally:
        await client.aclose()


async def test_accu_gebruikt_het_v3_endpoint_met_cangen() -> None:
    verzoeken: list[httpx.Request] = []
    client = _make_client(_routed(verzoeken))
    try:
        accu = await client.get_battery()
    finally:
        await client.aclose()

    battery_request = [r for r in verzoeken if "battery-status" in r.url.path][0]
    assert "/bff-web/v3/cars/SJNFAAZE0U0000001/battery-status" in str(battery_request.url)
    assert battery_request.url.params["canGen"] == "cangen2"

    assert accu.soc_percent == 64
    assert accu.range_km == 288
    assert accu.charging is True
    assert accu.plugged_in is True
    assert accu.battery_capacity_kwh == 87.0
    # Nissan levert geen accugezondheid -- bewust None in plaats van een gok.
    assert accu.state_of_health_percent is None
    assert accu.updated_at is not None
    assert accu.stale_minutes is not None


async def test_verse_meting_post_naar_de_car_adapter() -> None:
    verzoeken: list[httpx.Request] = []
    client = _make_client(_routed(verzoeken))
    try:
        await client.request_battery_refresh()
    finally:
        await client.aclose()

    post = [r for r in verzoeken if r.method == "POST"][0]
    assert "/car-adapter/v1/cars/SJNFAAZE0U0000001/actions/refresh-battery-status" in str(post.url)
    assert json.loads(post.content) == {"data": {"type": "RefreshBatteryStatus"}}


async def test_klimaat_starten_stuurt_een_heel_getal() -> None:
    verzoeken: list[httpx.Request] = []
    client = _make_client(_routed(verzoeken))
    try:
        await client.start_climate(21.0)
    finally:
        await client.aclose()

    post = [r for r in verzoeken if r.method == "POST"][0]
    assert "/car-adapter/v1/cars/SJNFAAZE0U0000001/actions/hvac-start" in str(post.url)
    body = json.loads(post.content)
    assert body == {
        "data": {
            "type": "HvacStart",
            "attributes": {"action": "start", "targetTemperature": 21},
        }
    }
    assert isinstance(body["data"]["attributes"]["targetTemperature"], int)


async def test_klimaat_stoppen_stuurt_geen_temperatuur() -> None:
    verzoeken: list[httpx.Request] = []
    client = _make_client(_routed(verzoeken))
    try:
        await client.stop_climate()
    finally:
        await client.aclose()

    body = json.loads([r for r in verzoeken if r.method == "POST"][0].content)
    assert body["data"]["attributes"] == {"action": "stop"}


async def test_klimaatstatus_wordt_gelezen() -> None:
    client = _make_client(_routed([]))
    try:
        status = await client.get_climate()
    finally:
        await client.aclose()
    assert status.running is True
    assert status.target_temp_c == 21.0


async def test_fout_in_een_200_wordt_als_fout_behandeld() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cars"):
            return httpx.Response(200, json={"data": [_CAR]})
        return httpx.Response(200, json={"errors": [{"detail": "vehicle is asleep"}]})

    client = _make_client(handler)
    try:
        with pytest.raises(ApiError) as exc:
            await client.request_battery_refresh()
        assert exc.value.code == "vehicle_asleep"
    finally:
        await client.aclose()


async def test_verlopen_abonnement_blokkeert_het_uitlezen() -> None:
    zonder_abonnement = dict(_CAR, services=[{"id": 319, "activationState": "EXPIRED"}])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [zonder_abonnement]})

    client = _make_client(handler)
    try:
        with pytest.raises(ApiError) as exc:
            await client.get_battery()
        assert "abonnement" in exc.value.message
    finally:
        await client.aclose()


async def test_bearer_header_wordt_meegestuurd() -> None:
    verzoeken: list[httpx.Request] = []
    client = _make_client(_routed(verzoeken))
    try:
        await client.get_battery()
    finally:
        await client.aclose()
    assert verzoeken[0].headers["Authorization"] == "Bearer nep-token"
    assert verzoeken[0].headers["Content-Type"] == "application/vnd.api+json"
