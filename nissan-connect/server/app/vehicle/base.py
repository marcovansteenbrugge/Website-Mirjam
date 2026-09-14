"""Abstracte auto-client.

Dit is het scharnierpunt van de hele backend: `main.py`, `jobs.py` en de tests
kennen *alleen* deze interface. Of er nu een echte Ariya aan de andere kant hangt
(`kamereon.KamereonVehicleClient`) of een simulatie (`mock.MockVehicleClient`),
de rest van de applicatie merkt geen verschil.

De modellen hieronder komen exact overeen met de JSON uit `CONTRACT.md`.
Velden die de auto niet levert zijn `None` -> `null`.
"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Final

from pydantic import BaseModel, ConfigDict, field_serializer

#: Toegestaan bereik voor de streeftemperatuur van de klimaatregeling.
#:
#: LET OP -- afwijking van CONTRACT.md: het contract noemt stappen van 0.5 graad,
#: maar de auto kent die niet. Nissan accepteert in `targetTemperature` uitsluitend
#: een heel getal van 16 t/m 26 (bevestigd door twee onafhankelijke implementaties
#: en door het onderzoeksrapport, sectie 4). Er bestaat ook geen aparte "zet
#: temperatuur"-opdracht: de temperatuur is een parameter van het *starten*.
#: De coordinator past het contract en de frontend hierop aan.
MIN_TARGET_TEMP_C = 16.0
MAX_TARGET_TEMP_C = 26.0
TARGET_TEMP_STEP_C = 1.0


def utcnow() -> datetime:
    """Huidige tijd in UTC (altijd tijdzone-bewust)."""
    return datetime.now(timezone.utc)


def compute_stale_minutes(updated_at: datetime | None, now: datetime | None = None) -> int | None:
    """Hoeveel minuten geleden kreeg Nissan deze meting van de auto?"""
    if updated_at is None:
        return None
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    reference = now or utcnow()
    delta = (reference - updated_at).total_seconds()
    return max(0, int(delta // 60))


class _ContractModel(BaseModel):
    """Basis met de datum-serialisatie die het contract voorschrijft."""

    model_config = ConfigDict(extra="forbid")

    @field_serializer("updated_at", check_fields=False)
    def _serialize_updated_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class VehicleInfo(_ContractModel):
    """`GET /api/vehicle`."""

    vin: str
    nickname: str | None = None
    model: str | None = None
    battery_capacity_kwh: float | None = None


class BatteryState(_ContractModel):
    """`GET /api/battery` -- de laatst bekende (gecachete) accustand."""

    soc_percent: int | None = None
    range_km: int | None = None
    charging: bool | None = None
    plugged_in: bool | None = None
    battery_capacity_kwh: float | None = None
    state_of_health_percent: int | None = None
    #: Resterende laadtijd in minuten (`chargingRemainingTime`).
    charging_remaining_minutes: int | None = None
    #: Beschikbare energie in de accu (`batteryAvailableEnergy`), zoals de auto
    #: hem geeft -- er wordt niets omgerekend.
    available_energy_kwh: float | None = None
    #: Accutemperatuur (`batteryTemperature`). De echte auto gaf hier 0 terwijl
    #: hij stond te laden; zie :func:`app.vehicle.kamereon.battery_temperature_c`
    #: voor waarom dat als "niet ondersteund" (`None`) wordt gelezen.
    battery_temperature_c: float | None = None
    updated_at: datetime | None = None
    #: Hoeveel minuten geleden de auto deze meting doorgaf. De client vult dit
    #: bij elke uitlezing opnieuw, met :func:`compute_stale_minutes`.
    stale_minutes: int | None = None


class ClimateState(_ContractModel):
    """`GET /api/climate`."""

    running: bool | None = None
    #: Wat je *wilt*: de streeftemperatuur waarmee het voorverwarmen draait.
    target_temp_c: float | None = None
    #: Wat het *nu* is: de gemeten binnentemperatuur (`internalTemperature`).
    #: Uitdrukkelijk iets anders dan `target_temp_c` -- op de echte auto stond
    #: de ene op 21 en de andere op 16,0. Ze mogen nooit door elkaar lopen.
    internal_temperature_c: float | None = None
    updated_at: datetime | None = None


class LocationState(_ContractModel):
    """`GET /api/location` -- waar Nissan de auto het laatst zag staan."""

    latitude: float | None = None
    longitude: float | None = None
    #: Kompasrichting in graden (0 = noord). Nissan noemt dit `gpsDirection`.
    heading_degrees: float | None = None
    updated_at: datetime | None = None
    stale_minutes: int | None = None


class OdometerState(_ContractModel):
    """`GET /api/odometer` -- de kilometerstand (`totalMileage`)."""

    total_km: int | None = None
    #: De echte auto stuurt hier géén tijdstempel mee; dan blijft dit `null`.
    updated_at: datetime | None = None


class TyrePressure(_ContractModel):
    """Eén wiel: druk in bar en of de auto hem in orde vindt."""

    bar: float | None = None
    #: `True` als de auto status 0 meldt. Onbekend blijft `None`.
    ok: bool | None = None


class TyreState(_ContractModel):
    """`GET /api/tyres` -- alle vier de wielen."""

    front_left: TyrePressure = TyrePressure()
    front_right: TyrePressure = TyrePressure()
    rear_left: TyrePressure = TyrePressure()
    rear_right: TyrePressure = TyrePressure()
    updated_at: datetime | None = None


#: De onderdelen waar `GET /api/capabilities` uitsluitsel over geeft, met de
#: Nederlandse omschrijving die in een foutmelding aan de eigenaar past.
#: Dit is *geen* lijst van wat wel of niet kan -- dat wordt gemeten.
CAPABILITY_LABELS: Final[dict[str, str]] = {
    "battery": "het uitlezen van de accu",
    "climate": "voorverwarmen",
    "location": "het opvragen van de locatie",
    "odometer": "het uitlezen van de kilometerstand",
    "tyres": "het uitlezen van de bandenspanning",
    "doors": "de deurvergrendeling",
    "charge_schedule": "het laadschema",
}


class Capabilities(_ContractModel):
    """`GET /api/capabilities` -- wat deze auto werkelijk levert.

    De interface hoort niets te tonen wat altijd faalt. Op de Ariya uit 2022
    geeft Nissan 403 op deuren en laadschema; die staan hier dus op `false`.
    """

    battery: bool = True
    climate: bool = True
    location: bool = True
    odometer: bool = True
    tyres: bool = True
    doors: bool = False
    charge_schedule: bool = False


class CapabilityCache:
    """Onthoudt per onderdeel of de auto het werkelijk teruggaf.

    Waarom onthouden en niet elke keer opnieuw proberen: zonder cache doet
    iedere paginaweergave een reeks verzoeken waarvan we het antwoord (403) al
    kennen. Dat is traag, het belast een API die toch al aan rate limiting doet,
    en het levert niets op -- een 403 op deuren wordt binnen dezelfde sessie
    geen 200.

    Waarom gemeten en niet hard opgeschreven: op een andere Ariya, met een ander
    abonnement of een ander modeljaar liggen de grenzen anders. Het resultaat van
    een echte aanroep is de enige betrouwbare bron.
    """

    def __init__(self, known: dict[str, bool] | None = None) -> None:
        self._known: dict[str, bool] = dict(known or {})

    def get(self, name: str) -> bool | None:
        """`True`/`False` als het bekend is, anders `None` (nog niet gemeten)."""
        return self._known.get(name)

    def remember(self, name: str, available: bool) -> None:
        self._known[name] = available

    def is_unavailable(self, name: str) -> bool:
        """Weten we zeker dat dit onderdeel niets oplevert?"""
        return self._known.get(name) is False

    def unknown(self) -> list[str]:
        """De onderdelen die nog nooit een echt antwoord hebben gegeven."""
        return [name for name in CAPABILITY_LABELS if name not in self._known]

    def snapshot(self, *, default: bool = True) -> dict[str, bool]:
        """Alle onderdelen als booleans, voor het contract.

        Wat nog niet gemeten kon worden (de auto sliep, het netwerk haperde)
        krijgt `default`. Standaard is dat `True`: een tijdelijke storing is
        geen bewijs dat de auto iets niet kan, en een knop die even niet werkt
        is minder erg dan een knop die spoorloos verdwijnt.
        """
        return {name: self._known.get(name, default) for name in CAPABILITY_LABELS}


class VehicleClient(abc.ABC):
    """Alles wat de app van een auto nodig heeft.

    Elke methode is `async` en mag het event-loop niet blokkeren.
    Bij problemen wordt een :class:`app.errors.ApiError` opgegooid met een van
    de contract-codes (`vehicle_asleep`, `nissan_auth_failed`, `upstream_error`, ...).
    """

    @abc.abstractmethod
    async def get_vehicle(self) -> VehicleInfo:
        """Statische gegevens van de auto (VIN, model, accucapaciteit)."""

    @abc.abstractmethod
    async def get_battery(self) -> BatteryState:
        """Gecachete accustand zoals Nissan die laatst van de auto kreeg. Snel."""

    @abc.abstractmethod
    async def request_battery_refresh(self) -> None:
        """Vraag de auto om een *verse* meting.

        Keert direct terug; de auto levert de nieuwe waarde pas later af bij
        Nissan. De aanroeper pollt daarna :meth:`get_battery` tot `updated_at`
        verandert.
        """

    @abc.abstractmethod
    async def get_climate(self) -> ClimateState:
        """Huidige status van de voorverwarming/-koeling."""

    @abc.abstractmethod
    async def start_climate(self, target_temp_c: float) -> None:
        """Start de klimaatregeling op `target_temp_c` graden Celsius."""

    @abc.abstractmethod
    async def stop_climate(self) -> None:
        """Zet de klimaatregeling uit."""

    @abc.abstractmethod
    async def get_location(self) -> LocationState:
        """Laatst bekende positie van de auto. Snel; maakt de auto niet wakker."""

    @abc.abstractmethod
    async def get_odometer(self) -> OdometerState:
        """Kilometerstand zoals Nissan die het laatst kreeg."""

    @abc.abstractmethod
    async def get_tyres(self) -> TyreState:
        """Bandenspanning van alle vier de wielen."""

    @abc.abstractmethod
    async def get_capabilities(self) -> Capabilities:
        """Wat deze auto werkelijk levert.

        Wordt vastgesteld door het echt te proberen en het antwoord te
        onthouden -- niet met een vaste lijst. Zie :class:`CapabilityCache`.
        """

    async def aclose(self) -> None:
        """Ruim netwerkverbindingen op. Standaard een no-op."""
        return None
