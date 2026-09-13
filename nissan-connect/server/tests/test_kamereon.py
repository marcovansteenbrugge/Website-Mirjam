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
