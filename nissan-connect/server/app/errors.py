"""Foutafhandeling volgens CONTRACT.md.

Elke fout met status >= 400 heeft exact deze vorm::

    {"error": {"code": "...", "message": "...", "retryable": true}}

De berichten zijn Nederlands en gericht aan de eigenaar van de auto,
niet aan een ontwikkelaar.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel

ErrorCode = Literal[
    "unauthorized",
    "nissan_auth_failed",
    "vehicle_asleep",
    "rate_limited",
    "not_plugged_in",
    "upstream_error",
    "invalid_request",
]

#: code -> (http-status, standaardbericht, retryable)
ERROR_CATALOG: Final[dict[str, tuple[int, str, bool]]] = {
    "unauthorized": (
        401,
        "Geen toegang — je token ontbreekt of klopt niet.",
        False,
    ),
    "nissan_auth_failed": (
        502,
        "Inloggen bij Nissan lukt niet. Controleer je Nissan-gebruikersnaam en wachtwoord.",
        False,
    ),
    "vehicle_asleep": (
        503,
        "De auto reageert niet — waarschijnlijk in slaapstand.",
        True,
    ),
    "rate_limited": (
        429,
        "Even wachten: de auto is kort geleden al opgevraagd.",
        True,
    ),
    "not_plugged_in": (
        409,
        "De auto hangt niet aan de lader.",
        False,
    ),
    "upstream_error": (
        502,
        "Nissan is op dit moment niet bereikbaar. Probeer het straks nog eens.",
        True,
    ),
    "invalid_request": (
        400,
        "Dat verzoek klopt niet.",
        False,
    ),
}


class ErrorBody(BaseModel):
    """Het `error`-object uit het contract."""

    code: str
    message: str
    retryable: bool


class ErrorResponse(BaseModel):
    """De volledige foutrespons uit het contract."""

    error: ErrorBody


class ApiError(Exception):
    """Fout die rechtstreeks vertaald wordt naar het contract-foutschema."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        status_code: int | None = None,
        retryable: bool | None = None,
    ) -> None:
        default_status, default_message, default_retryable = ERROR_CATALOG[code]
        self.code: str = code
        self.message: str = message or default_message
        self.status_code: int = status_code or default_status
        self.retryable: bool = default_retryable if retryable is None else retryable
        super().__init__(f"{self.code}: {self.message}")

    def to_dict(self) -> dict[str, Any]:
        """Serialiseer naar het contract-foutschema."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
            }
        }


class FeatureUnavailable(ApiError):
    """Deze auto (of dit abonnement) levert dit onderdeel simpelweg niet.

    Nissan antwoordt op de Ariya uit 2022 met **403** op deuren, laadschema,
    laadmodus en energie, en met **404** op onderhoud. Dat is geen storing en
    geen inlogprobleem: het komt morgen niet vanzelf goed. Daarom een eigen
    fouttype, zodat drie dingen tegelijk kloppen:

    1. de eigenaar leest "deze auto ondersteunt dit niet" in plaats van
       "er ging iets mis";
    2. :meth:`app.vehicle.base.VehicleClient.get_capabilities` kan dit
       onthouden en het onderdeel niet nog eens bevragen;
    3. het blijft een :class:`ApiError`, dus de bestaande foutafhandeling en
       het contract-foutschema gelden onveranderd.

    De code blijft `upstream_error` -- het contract kent geen aparte code en dit
    bestand mag niet buiten dat lijstje treden. De status is 501 (Not
    Implemented): dit verzoek is niet uit te voeren voor deze auto.
    """

    def __init__(self, wat: str, message: str | None = None) -> None:
        super().__init__(
            "upstream_error",
            message
            or (
                f"Deze auto ondersteunt {wat} niet. Nissan wijst het verzoek af; "
                "waarschijnlijk zit dit onderdeel niet in deze Ariya of niet in "
                "je NissanConnect-abonnement."
            ),
            status_code=501,
            retryable=False,
        )
        #: Waar het over ging, voor de logs en de capability-administratie.
        self.wat = wat
