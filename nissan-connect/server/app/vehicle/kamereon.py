"""Echte client tegen de NissanConnect-backend (Kamereon).

HERKOMST
========
De constanten en de volgorde van de HTTP-stappen zijn overgenomen uit het
`kamereon/`-package van **dan-r/HomeAssistant-NissanConnect** (MIT-licentie),
bestanden `kamereon.py` en `kamereon_const.py`. Die code gebruikt `requests` +
`requests_oauthlib`; hier is de flow herschreven naar `httpx.AsyncClient`, zodat
er niets blokkeert en er geen extra afhankelijkheden meegesleept worden.
Dat werk bouwt zelf voort op `mitchellrj/kamereon-python` en `Tobiaswk`.

Aanvullend gecontroleerd tegen `../../nissan-research/API-RESEARCH.md`
(secties 2, 3, 4, 6 en 8), dat dezelfde constanten uit een tweede, onafhankelijke
implementatie (evcc, Go) bevestigt.

CORRECTIE OP DE OORSPRONKELIJKE OPDRACHT
----------------------------------------
De opdracht vroeg om "Gigya login -> JWT -> Kamereon". Dat is **Renault**, niet
Nissan: `renault-api` logt in op `accounts.eu1.gigya.com` met een Renault-API-key.
Nissan EU gebruikte ForgeRock/OpenAM en sinds eind augustus 2026 MyNISSAN
"OneID": een WSO2 Identity Server op `login.mynissan-account.com` met OAuth2
authorization-code + PKCE, zonder client secret en zonder API-key. Het
Kamereon-datavlak erachter is ongewijzigd. Er is bewust géén Gigya-code verzonnen.

STATUS VAN DE VERIFICATIE -- LEES DIT
-------------------------------------
Niets hieronder is tegen een echte Nissan-server getest: dat vraagt om echte
inloggegevens en een echte auto. Wat er wél is: twee onafhankelijk geschreven
implementaties die het over elke constante eens zijn. Behandel dit dus als
goed onderbouwd maar onbevestigd.

Wat bewust NIET is ingevuld (zie de `NotImplementedError`-plekken):

1. Halve graden als streeftemperatuur. De auto kent ze niet; zie
   :data:`app.vehicle.base.TARGET_TEMP_STEP_C`.
2. Andere regio's dan Europa: die instellingen staan in geen enkele bron.
3. `state_of_health_percent`: geen enkele client leest een SOH-veld uit. Blijft
   `None` (het contract staat `null` toe). De echte route naar accugezondheid is
   een OBD-II-dongle, niet deze API.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Final
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from ..errors import ApiError
from ..redaction import Redactor
from .base import (
    BatteryState,
    ClimateState,
    VehicleClient,
    VehicleInfo,
    compute_stale_minutes,
)

_LOGGER = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Geverifieerde constanten -- letterlijk uit kamereon_const.py (SETTINGS_MAP)
# --------------------------------------------------------------------------
EU_SETTINGS: Final[dict[str, str]] = {
    "client_id": "ZM3WK7ax1OtQKYQ8Qqzcv5VgiA8a",
    "scope": "openid name profile email offline_access",
    "kamereon_scope": "openid profile vehicles",
    "auth_base_url": "https://login.mynissan-account.com/",
    "redirect_uri": "com://wso2.service.nci",
    "auth_brand": "Nissan",
    "auth_client": "mynissanapp",
    "auth_platform": "Android",
    "auth_locale": "en_GB",
    "car_adapter_base_url": "https://alliance-platform-caradapter-prod.apps.eu2.kamereon.io/car-adapter/",
    "notifications_base_url": "https://alliance-platform-notifications-prod.apps.eu2.kamereon.io/notifications/",
    "user_adapter_base_url": "https://alliance-platform-usersadapter-prod.apps.eu2.kamereon.io/user-adapter/",
    "user_base_url": "https://nci-bff-web-prod.apps.eu2.kamereon.io/bff-web/",
}

#: Landen die in de bron onder de EU-instellingen vallen. Alleen 'EU' is
#: geverifieerd; deze lijst mapt landcodes naar diezelfde set.
EU_COUNTRIES: Final[frozenset[str]] = frozenset(
    {
        "EU", "NL", "BE", "LU", "DE", "AT", "CH", "FR", "IT", "ES", "PT",
        "GB", "UK", "IE", "DK", "SE", "NO", "FI", "PL", "CZ", "SK", "HU",
        "SI", "HR", "RO", "BG", "GR", "EE", "LV", "LT",
    }
)

JSON_API_CONTENT_TYPE: Final[str] = "application/vnd.api+json"

#: Feature-ID's uit `Feature` in kamereon_const.py. Deze lijst is tegelijk de
#: *abonnementsstatus*: loopt NissanConnect Services af, dan kun je nog gewoon
#: inloggen en de auto zien, maar staan deze niet meer op ACTIVATED.
FEATURE_BATTERY_STATUS: Final[str] = "319"
FEATURE_CLIMATE_ON_OFF: Final[str] = "366"
FEATURE_INTERIOR_TEMP_SETTINGS: Final[str] = "307"
FEATURE_TEMPERATURE: Final[str] = "2042"

_MAX_REDIRECTS = 10

#: De Kamereon-API is werkelijk traag; evcc hanteert 120 s met de opmerking
#: "api is unbelievably slow when retrieving status". Een krappe timeout ziet
#: eruit als een kapotte auto terwijl er niets aan de hand is.
_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=15.0)


def settings_for_region(region: str) -> dict[str, str]:
    """Geef de backend-instellingen voor een regio.

    Alleen de EU-set is geverifieerd. Voor een andere regio wordt géén
    URL of client-id verzonnen.
    """
    if region.strip().upper() in EU_COUNTRIES:
        return EU_SETTINGS
    raise NotImplementedError(
        "ONGEVERIFIEERD: alleen de Nissan EU-backend staat in de geraadpleegde "
        f"broncode (SETTINGS_MAP['nissan']['EU']). Voor regio {region!r} zijn "
        "client_id, auth_base_url en de Kamereon-hosts onbekend. Deze zijn "
        "bewust niet geraden."
    )


class _LoginFormParser(HTMLParser):
    """Haalt het WSO2-inlogformulier uit de HTML-pagina.

    Overgenomen uit `_LoginFormParser` in kamereon.py: het juiste formulier is
    dat met zowel een `sessionDataKey`- als een `password`-veld.
    """

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self._form = {
                "action": attributes.get("action"),
                "method": (attributes.get("method") or "get").lower(),
                "inputs": {},
            }
        elif tag == "input" and self._form is not None:
            name = attributes.get("name")
            if name:
                self._form["inputs"][name] = attributes.get("value", "") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._form is not None:
            self.forms.append(self._form)
            self._form = None

    @property
    def login_form(self) -> dict[str, Any] | None:
        for form in self.forms:
            inputs = form["inputs"]
            if "sessionDataKey" in inputs and "password" in inputs:
                return form
        return None


class KamereonVehicleClient(VehicleClient):
    """Asynchrone client tegen NissanConnect EU.

    Alle netwerk-I/O gaat via één gedeelde :class:`httpx.AsyncClient`. Tokens
    worden in het geheugen gecachet en automatisch ververst.
    """

    def __init__(
        self,
        username: str,
        password: str,
        *,
        region: str = "NL",
        vin: str | None = None,
        client: httpx.AsyncClient | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        if not username or not password:
            raise ApiError(
                "nissan_auth_failed",
                "Er zijn geen Nissan-inloggegevens ingesteld op de server.",
            )
        self._settings = settings_for_region(region)
        self._username = username
        self._password = password
        self._pinned_vin = vin.upper() if vin else None

        self._redactor = redactor or Redactor()
        self._redactor.add(password)
        self._redactor.add(username)

        self._client = client or httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": "nissan-connect-personal/1.0"},
        )
        self._owns_client = client is None

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0
        self._user_id: str | None = None
        self._vehicle_data: dict[str, Any] | None = None
        self._auth_lock = asyncio.Lock()
        #: Zijn de inloggegevens afgewezen? Dan niet blijven proberen: WSO2 kent
        #: account-lockout en CAPTCHA-na-N-pogingen, en dit is een echt
        #: Nissan-account. Eén duidelijke fout is beter dan een geblokkeerd account.
        self._auth_blocked: ApiError | None = None

    # ------------------------------------------------------------------ #
    # Foutvertaling
    # ------------------------------------------------------------------ #

    def _scrub(self, text: str) -> str:
        return self._redactor.scrub(text)

    def _fail_upstream(self, context: str, detail: str = "") -> ApiError:
        """Log veilig en geef een nette contract-fout terug."""
        _LOGGER.warning("Nissan-fout bij %s: %s", context, self._scrub(detail)[:300])
        return ApiError("upstream_error")

    @staticmethod
    def _classify_status(status_code: int) -> ApiError | None:
        if status_code in (401, 403):
            return ApiError(
                "nissan_auth_failed",
                "Nissan accepteert de sessie niet meer. Controleer je Nissan-account.",
            )
        if status_code == 429:
            return ApiError(
                "rate_limited",
                "Nissan heeft te veel verzoeken ontvangen. Probeer het straks nog eens.",
            )
        if status_code in (408, 502, 503, 504):
            return ApiError("vehicle_asleep")
        if status_code >= 400:
            return ApiError("upstream_error")
        return None

    # ------------------------------------------------------------------ #
    # Authenticatie: OAuth2 + PKCE tegen WSO2, daarna omwisselen naar Kamereon
    # ------------------------------------------------------------------ #

    @staticmethod
    def _pkce_pair() -> tuple[str, str]:
        """Genereer (verifier, challenge) volgens PKCE S256."""
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def _is_auth_url(self, url: str) -> bool:
        """Blijf tijdens het inloggen op de Nissan-inloghost."""
        try:
            expected = urlparse(self._settings["auth_base_url"])
            parsed = urlparse(url)
        except ValueError:
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname == expected.hostname
            and (parsed.port or 443) == (expected.port or 443)
        )

    async def _follow_login_redirects(self, response: httpx.Response) -> httpx.Response:
        for _ in range(_MAX_REDIRECTS):
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                target = urljoin(str(response.url), location)
                if not self._is_auth_url(target):
                    raise self._fail_upstream("inlogredirect", f"onverwachte host {target}")
                response = await self._client.get(target)
                continue
            if response.status_code < 400 and self._is_auth_url(str(response.url)):
                return response
            break
        raise self._fail_upstream("inlogpagina laden", f"status {response.status_code}")

    async def _follow_authorization_redirects(self, response: httpx.Response) -> str:
        expected = urlparse(self._settings["redirect_uri"])
        for _ in range(_MAX_REDIRECTS):
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                target = urljoin(str(response.url), location)
                parsed = urlparse(target)
                if (parsed.scheme, parsed.netloc) == (expected.scheme, expected.netloc):
                    return target
                if not self._is_auth_url(target):
                    raise self._fail_upstream("autorisatieredirect", f"onverwachte host {target}")
                response = await self._client.get(target)
                continue
            if response.status_code < 400:
                parser = _LoginFormParser()
                parser.feed(response.text)
                if parser.login_form is not None:
                    # WSO2 geeft bij verkeerde inloggegevens geen OAuth-fout terug,
                    # maar rendert het inlogformulier opnieuw. Dát is het signaal.
                    raise ApiError(
                        "nissan_auth_failed",
                        "Nissan accepteert je gebruikersnaam of wachtwoord niet. "
                        "Controleer of je met dezelfde gegevens in de MyNISSAN-app "
                        "kunt inloggen.",
                    )
            break

        # Geen callback én geen inlogformulier: dit is géén wachtwoordprobleem.
        # Meestal wacht er een akkoordverklaring of verificatie in de app zelf.
        raise ApiError(
            "nissan_auth_failed",
            "Het inloggen bij Nissan liep vast. Open de MyNISSAN-app of -website, "
            "bevestig eventuele openstaande voorwaarden of verificaties, en probeer "
            "het daarna opnieuw.",
        )

    async def _authorization_code(self) -> tuple[str, str]:
        """Doorloop het inlogformulier en lever (code, verifier)."""
        verifier, challenge = self._pkce_pair()
        state = secrets.token_urlsafe(32)

        try:
            response = await self._client.get(
                urljoin(self._settings["auth_base_url"], "oauth2/authorize"),
                params={
                    "response_type": "code",
                    "redirect_uri": self._settings["redirect_uri"],
                    "client_id": self._settings["client_id"],
                    "state": state,
                    "scope": self._settings["scope"],
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "locale": self._settings["auth_locale"],
                    "brand": self._settings["auth_brand"],
                    "client": self._settings["auth_client"],
                },
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            )
        except httpx.HTTPError as exc:
            raise self._fail_upstream("verbinden met Nissan-login", str(exc)) from None

        response = await self._follow_login_redirects(response)

        parser = _LoginFormParser()
        parser.feed(response.text)
        form = parser.login_form
        if form is None or not form["action"]:
            raise self._fail_upstream("inlogformulier zoeken", "formulier niet gevonden")

        login_data: dict[str, str] = dict(form["inputs"])
        region_code = login_data.get("regionCode", "")
        login_data.update(
            {
                "userName": self._username,
                "username": f"{region_code}/{self._username}" if region_code else self._username,
                "password": self._password,
            }
        )

        form_url = urljoin(str(response.url), form["action"])
        if not self._is_auth_url(form_url):
            raise self._fail_upstream("inlogformulier versturen", f"onverwachte host {form_url}")
        origin = urlparse(form_url)

        try:
            post_response = await self._client.post(
                form_url,
                data=login_data,
                headers={
                    "Origin": f"{origin.scheme}://{origin.netloc}",
                    "Referer": str(response.url),
                },
            )
        except httpx.HTTPError as exc:
            raise self._fail_upstream("inloggen bij Nissan", str(exc)) from None

        callback_url = await self._follow_authorization_redirects(post_response)
        callback = urlparse(callback_url)
        query = parse_qs(callback.query)

        if query.get("state", [None])[0] != state:
            raise self._fail_upstream("inlogcallback", "state komt niet overeen")
        code = query.get("code", [None])[0]
        if not code:
            raise ApiError("nissan_auth_failed")
        return code, verifier

    def _parse_token_payload(
        self, response: httpx.Response, what: str, *, need_id_token: bool = False
    ) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError:
            raise self._fail_upstream(what, "ongeldige JSON") from None
        if not isinstance(data, dict):
            raise self._fail_upstream(what, "onverwacht antwoordtype")
        if response.status_code >= 400 or data.get("error") or not data.get("access_token"):
            if response.status_code in (400, 401, 403):
                raise ApiError("nissan_auth_failed")
            raise self._fail_upstream(what, f"status {response.status_code}")
        if need_id_token and not data.get("id_token"):
            raise self._fail_upstream(what, "id_token ontbreekt")
        return data

    async def _exchange_wso2_token(self, code: str, verifier: str) -> dict[str, Any]:
        response = await self._client.post(
            urljoin(self._settings["auth_base_url"], "oauth2/token"),
            data={
                "redirect_uri": self._settings["redirect_uri"],
                "grant_type": "authorization_code",
                "client_id": self._settings["client_id"],
                "code": code,
                "code_verifier": verifier,
                "scope": self._settings["scope"],
            },
        )
        return self._parse_token_payload(response, "OneID-token ophalen", need_id_token=True)

    async def _exchange_kamereon_token(self, wso2_id_token: str) -> dict[str, Any]:
        response = await self._client.post(
            urljoin(self._settings["user_base_url"], "v1/oauth2/access_token"),
            params={"platform": self._settings["auth_platform"]},
            headers={
                "Authorization": wso2_id_token,
                "Content-Type": JSON_API_CONTENT_TYPE,
            },
        )
        return self._parse_token_payload(response, "Kamereon-token ophalen")

    async def _refresh_kamereon_token(self) -> dict[str, Any]:
        if not self._refresh_token:
            raise ApiError("nissan_auth_failed", "Geen vernieuwingstoken beschikbaar.")
        response = await self._client.post(
            urljoin(self._settings["user_base_url"], "v1/oauth2/refresh-token"),
            params={"platform": self._settings["auth_platform"]},
            headers={
                "Authorization": self._refresh_token,
                "Content-Type": JSON_API_CONTENT_TYPE,
            },
            json={"scope": self._settings["kamereon_scope"]},
        )
        return self._parse_token_payload(response, "Kamereon-token vernieuwen")

    def _install_token(self, payload: dict[str, Any]) -> None:
        expires_in = int(payload.get("expires_in", 3600) or 3600)
        self._access_token = str(payload["access_token"])
        self._refresh_token = payload.get("refresh_token") or self._refresh_token
        # 60 seconden marge, zodat we nooit met een net-verlopen token vertrekken.
        self._expires_at = time.monotonic() + max(30, expires_in - 60)
        self._redactor.add(self._access_token)
        if self._refresh_token:
            self._redactor.add(self._refresh_token)

    async def _login(self) -> None:
        code, verifier = await self._authorization_code()
        wso2 = await self._exchange_wso2_token(code, verifier)
        self._install_token(await self._exchange_kamereon_token(str(wso2["id_token"])))
        _LOGGER.info("Opnieuw ingelogd bij Nissan (token vernieuwd).")

    async def _ensure_token(self, *, force: bool = False) -> str:
        """Zorg voor een geldig Kamereon-token; log opnieuw in als het moet."""
        async with self._auth_lock:
            if self._auth_blocked is not None:
                # Inloggegevens zijn eerder afgewezen. Niet opnieuw proberen.
                raise self._auth_blocked
            if not force and self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            if self._refresh_token and not force:
                try:
                    self._install_token(await self._refresh_kamereon_token())
                    return self._access_token or ""
                except ApiError:
                    _LOGGER.debug("Token vernieuwen mislukt; opnieuw inloggen.")
                except httpx.HTTPError:
                    _LOGGER.debug("Netwerkfout bij vernieuwen; opnieuw inloggen.")
            try:
                await self._login()
            except ApiError as exc:
                if exc.code == "nissan_auth_failed":
                    self._auth_blocked = exc
                raise
            return self._access_token or ""

    # ------------------------------------------------------------------ #
    # Generiek verzoek met automatische her-authenticatie
    # ------------------------------------------------------------------ #

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        last_error: ApiError | None = None
        for attempt in range(2):
            token = await self._ensure_token(force=attempt > 0)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": JSON_API_CONTENT_TYPE,
                "Accept": JSON_API_CONTENT_TYPE,
            }
            try:
                response = await self._client.request(
                    method, url, params=params, json=json_body, headers=headers
                )
            except httpx.TimeoutException as exc:
                raise ApiError(
                    "vehicle_asleep",
                    "De auto reageert niet — waarschijnlijk in slaapstand.",
                ) from exc
            except httpx.HTTPError as exc:
                raise self._fail_upstream(f"{method} {urlparse(url).path}", str(exc)) from None

            if response.status_code in (401, 403) and attempt == 0:
                last_error = ApiError("nissan_auth_failed")
                continue

            status_error = self._classify_status(response.status_code)
            if status_error is not None:
                _LOGGER.warning(
                    "Nissan antwoordde %s op %s %s",
                    response.status_code,
                    method,
                    urlparse(url).path,
                )
                raise status_error

            if not response.content:
                return {}
            try:
                body = response.json()
            except ValueError:
                raise self._fail_upstream(f"{method} {urlparse(url).path}", "ongeldige JSON") from None
            if not isinstance(body, dict):
                return {"data": body}
            if body.get("errors"):
                raise self._translate_api_errors(body["errors"])
            return body

        raise last_error or ApiError("upstream_error")

    @staticmethod
    def _translate_api_errors(errors: Any) -> ApiError:
        """Vertaal een JSON:API-`errors`-blok naar een contract-fout."""
        text = str(errors).lower()
        if any(marker in text for marker in ("not plugged", "unplugged", "plug_not")):
            return ApiError("not_plugged_in")
        if "sleep" in text or "unavailable" in text or "timeout" in text or "not responding" in text:
            return ApiError("vehicle_asleep")
        _LOGGER.warning("Nissan meldde een fout: %s", str(errors)[:300])
        return ApiError("upstream_error")

    # ------------------------------------------------------------------ #
    # Vaste gegevens: gebruiker + voertuig
    # ------------------------------------------------------------------ #

    async def _get_user_id(self) -> str:
        """GET {user_adapter_base_url}v1/users/current -> userId (geverifieerd)."""
        if self._user_id:
            return self._user_id
        body = await self._request(
            "GET", f"{self._settings['user_adapter_base_url']}v1/users/current"
        )
        user_id = body.get("userId")
        if not user_id:
            raise self._fail_upstream("gebruiker ophalen", "userId ontbreekt")
        self._user_id = str(user_id)
        return self._user_id

    async def _get_vehicle_data(self) -> dict[str, Any]:
        """GET {user_base_url}v5/users/{userId}/cars -> data[] (geverifieerd)."""
        if self._vehicle_data is not None:
            return self._vehicle_data
        user_id = await self._get_user_id()
        body = await self._request(
            "GET", f"{self._settings['user_base_url']}v5/users/{user_id}/cars"
        )
        cars = body.get("data") or []
        if not cars:
            raise ApiError(
                "upstream_error",
                "Er staat geen auto op dit Nissan-account. Koppel de auto eerst in "
                "de MyNISSAN-app; via deze weg kan dat niet.",
                retryable=False,
            )
        if self._pinned_vin:
            for car in cars:
                if str(car.get("vin", "")).upper() == self._pinned_vin:
                    self._vehicle_data = car
                    return car
            raise ApiError(
                "upstream_error",
                "De ingestelde VIN staat niet op dit Nissan-account.",
            )
        self._vehicle_data = cars[0]
        return cars[0]

    @staticmethod
    def _active_features(car: dict[str, Any]) -> set[str]:
        """De diensten die op dit moment écht actief zijn voor deze auto."""
        return {
            str(service.get("id"))
            for service in car.get("services", [])
            if service.get("activationState") == "ACTIVATED"
        }

    def _require_feature(self, car: dict[str, Any], feature_id: str, wat: str) -> None:
        """Controleer of een dienst actief is, met een begrijpelijke uitleg als dat niet zo is.

        Dit is de stille killer van deze API: als het NissanConnect-abonnement
        afloopt, kun je nog gewoon inloggen en staat de auto er nog gewoon in --
        alleen `services[]` zegt niet meer ACTIVATED, en alles geeft lege of
        foutieve antwoorden terug. Die situatie mag niet verward worden met een
        netwerkstoring of een slapende auto.
        """
        active = self._active_features(car)
        if feature_id in active:
            return
        if not active:
            raise ApiError(
                "upstream_error",
                "Er staan geen actieve NissanConnect-diensten op deze auto. "
                "Waarschijnlijk is het NissanConnect-abonnement verlopen — dat is "
                "te zien (en te verlengen) in de MyNISSAN-app.",
                retryable=False,
            )
        raise ApiError(
            "upstream_error",
            f"{wat} is niet beschikbaar voor deze auto. Controleer in de MyNISSAN-app "
            "of deze dienst nog in je abonnement zit.",
            retryable=False,
        )

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    # ------------------------------------------------------------------ #
    # Contract-methodes
    # ------------------------------------------------------------------ #

    async def get_vehicle(self) -> VehicleInfo:
        car = await self._get_vehicle_data()
        model_name = car.get("modelName")
        model_year = car.get("modelYear")
        model = " ".join(str(p) for p in (model_name, model_year) if p) or None
        capacity = car.get("batteryCapacity")
        return VehicleInfo(
            vin=str(car.get("vin", "")).upper(),
            nickname=car.get("nickname") or model_name,
            model=model,
            battery_capacity_kwh=float(capacity) if isinstance(capacity, (int, float)) else None,
        )

    async def get_battery(self) -> BatteryState:
        """Accustand via de v3-API die de Ariya gebruikt.

        Geverifieerd: `fetch_battery_status_ariya()` doet
        `GET {user_base_url}v3/cars/{vin}/battery-status?canGen={canGeneration}`.
        """
        car = await self._get_vehicle_data()
        self._require_feature(car, FEATURE_BATTERY_STATUS, "Het uitlezen van de accu")
        vin = str(car.get("vin", "")).upper()
        can_gen = car.get("canGeneration")

        params: dict[str, Any] = {}
        if can_gen is not None:
            params["canGen"] = can_gen

        body = await self._request(
            "GET",
            f"{self._settings['user_base_url']}v3/cars/{vin}/battery-status",
            params=params,
        )
        attributes = (body.get("data") or {}).get("attributes") or {}

        soc = attributes.get("batteryLevel")
        # Geverifieerd: de v3-API levert het bereik als `batteryAutonomy`,
        # met `rangeHvacOn` als alternatief.
        range_km = attributes.get("batteryAutonomy")
        if range_km is None:
            range_km = attributes.get("rangeHvacOn")

        # plugStatus / chargingStatus: 0 = niet, 1 = wel, -1 = fout (PluggedStatus /
        # ChargingStatus in kamereon_const.py).
        plug_status = attributes.get("plugStatus")
        charge_status = attributes.get("chargingStatus")
        if charge_status is None:
            charge_status = attributes.get("chargeStatus")

        capacity = attributes.get("batteryCapacity")
        if not isinstance(capacity, (int, float)):
            capacity = car.get("batteryCapacity")

        updated_at = self._parse_timestamp(attributes.get("lastUpdateTime"))

        return BatteryState(
            soc_percent=int(round(soc)) if isinstance(soc, (int, float)) else None,
            range_km=int(round(range_km)) if isinstance(range_km, (int, float)) else None,
            charging=bool(charge_status == 1) if charge_status is not None else None,
            plugged_in=bool(plug_status == 1) if plug_status is not None else None,
            battery_capacity_kwh=float(capacity) if isinstance(capacity, (int, float)) else None,
            # ONGEVERIFIEERD: geen enkele geraadpleegde bron leest een
            # state-of-health-veld uit battery-status. Feature-ID 323
            # (BATTERY_STATE_OF_HEALTH_PERCENT) bestaat wel, maar het bijbehorende
            # responseveld is nergens vastgelegd. Daarom bewust `None` i.p.v. gokken.
            state_of_health_percent=None,
            updated_at=updated_at,
            stale_minutes=compute_stale_minutes(updated_at),
        )

    async def request_battery_refresh(self) -> None:
        """POST .../actions/refresh-battery-status (geverifieerd).

        Nissan bevestigt alleen de opdracht; de auto meldt de nieuwe waarde later.
        De aanroeper pollt daarna :meth:`get_battery`.
        """
        car = await self._get_vehicle_data()
        self._require_feature(car, FEATURE_BATTERY_STATUS, "Het uitlezen van de accu")
        vin = str(car.get("vin", "")).upper()
        await self._request(
            "POST",
            f"{self._settings['car_adapter_base_url']}v1/cars/{vin}/actions/refresh-battery-status",
            json_body={"data": {"type": "RefreshBatteryStatus"}},
        )

    async def get_climate(self) -> ClimateState:
        """GET {car_adapter_base_url}v1/cars/{vin}/hvac-status (geverifieerd)."""
        car = await self._get_vehicle_data()
        self._require_feature(car, FEATURE_CLIMATE_ON_OFF, "Voorverwarmen")
        vin = str(car.get("vin", "")).upper()
        body = await self._request(
            "GET", f"{self._settings['car_adapter_base_url']}v1/cars/{vin}/hvac-status"
        )
        attributes = (body.get("data") or {}).get("attributes") or {}

        hvac_status = attributes.get("hvacStatus")
        running = (hvac_status == "on") if hvac_status is not None else None
        target = attributes.get("nextTargetTemperature")

        return ClimateState(
            running=running,
            target_temp_c=float(target) if isinstance(target, (int, float)) else None,
            updated_at=self._parse_timestamp(attributes.get("lastUpdateTime")),
        )

    async def start_climate(self, target_temp_c: float) -> None:
        """POST .../actions/hvac-start met `action: start` (geverifieerd)."""
        if float(target_temp_c) != float(int(target_temp_c)):
            raise NotImplementedError(
                "ONGEVERIFIEERD: halve graden. De auto kent alleen hele graden 16..26 in "
                "'targetTemperature' (kamereon.py set_hvac_status raakt hierop een "
                "ValueError; de HA-climate-entiteit gebruikt target_temperature_step=1; "
                "API-RESEARCH.md sectie 4 bevestigt dit uit een tweede implementatie). "
                "Of Nissan 21.5 accepteert, afrondt of weigert is onbekend en wordt hier "
                "niet geraden. De API-laag hoort halve graden al eerder te weigeren; deze "
                "controle is het vangnet."
            )

        car = await self._get_vehicle_data()
        self._require_feature(car, FEATURE_CLIMATE_ON_OFF, "Voorverwarmen")
        vin = str(car.get("vin", "")).upper()

        # Sommige auto's mogen de klimaatregeling wel aanzetten, maar geen eigen
        # streeftemperatuur kiezen. Dat blokkeert het starten niet -- de auto
        # gebruikt dan zijn eigen instelling.
        active = self._active_features(car)
        if not (active & {FEATURE_TEMPERATURE, FEATURE_INTERIOR_TEMP_SETTINGS}):
            _LOGGER.info(
                "Deze auto ondersteunt geen eigen streeftemperatuur; de auto kiest zelf."
            )

        await self._request(
            "POST",
            f"{self._settings['car_adapter_base_url']}v1/cars/{vin}/actions/hvac-start",
            json_body={
                "data": {
                    "type": "HvacStart",
                    "attributes": {
                        "action": "start",
                        "targetTemperature": int(target_temp_c),
                    },
                }
            },
        )

    async def stop_climate(self) -> None:
        """POST .../actions/hvac-start met `action: stop` (geverifieerd).

        Ja, ook stoppen gaat via het `hvac-start`-pad -- zo staat het in de bron.
        """
        car = await self._get_vehicle_data()
        self._require_feature(car, FEATURE_CLIMATE_ON_OFF, "Voorverwarmen")
        vin = str(car.get("vin", "")).upper()
        # Bewust géén targetTemperature meesturen bij "stop".
        await self._request(
            "POST",
            f"{self._settings['car_adapter_base_url']}v1/cars/{vin}/actions/hvac-start",
            json_body={
                "data": {
                    "type": "HvacStart",
                    "attributes": {"action": "stop"},
                }
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
