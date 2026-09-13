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
    updated_at: datetime | None = None
    #: Hoeveel minuten geleden de auto deze meting doorgaf. De client vult dit
    #: bij elke uitlezing opnieuw, met :func:`compute_stale_minutes`.
    stale_minutes: int | None = None


class ClimateState(_ContractModel):
    """`GET /api/climate`."""

    running: bool | None = None
    target_temp_c: float | None = None
    updated_at: datetime | None = None


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

    async def aclose(self) -> None:
        """Ruim netwerkverbindingen op. Standaard een no-op."""
        return None
