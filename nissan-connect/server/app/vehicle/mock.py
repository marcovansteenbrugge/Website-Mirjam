"""Gesimuleerde Ariya (`MOCK=1`).

Doel: de frontend kan volledig los ontwikkeld en gedemonstreerd worden, inclusief
de vervelende paden -- trage commando's en een auto die niet wakker wil worden.

Gedrag:
* het laadpercentage zakt langzaam weg (sluimerverbruik) en loopt op tijdens laden;
* een geforceerde meting (`request_battery_refresh`) levert pas na ~8 seconden
  een nieuwe `updated_at` op;
* de klimaatregeling meldt zich pas na ~20 seconden als `running: true`;
* af en toe faalt een commando met `vehicle_asleep`, zodat de foutafhandeling
  van de frontend ook echt geoefend wordt.

Alle timings zijn injecteerbaar zodat de tests niet hoeven te wachten.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from ..errors import ApiError
from .base import BatteryState, ClimateState, VehicleClient, VehicleInfo, compute_stale_minutes

#: Plausibele Ariya 87 kWh.
DEFAULT_CAPACITY_KWH = 87.0
DEFAULT_WLTP_RANGE_KM = 500.0


class MockVehicleClient(VehicleClient):
    """Simuleert een Nissan Ariya zonder ook maar iets naar Nissan te sturen."""

    def __init__(
        self,
        *,
        vin: str = "SJNFAAZE0U0000000",
        nickname: str = "Ariya",
        model: str = "Ariya 87kWh",
        capacity_kwh: float = DEFAULT_CAPACITY_KWH,
        start_soc: float = 72.0,
        state_of_health_percent: int | None = 98,
        idle_drain_percent_per_hour: float = 0.4,
        charge_percent_per_hour: float = 11.0,
        charging: bool = False,
        plugged_in: bool = True,
        climate_spool_seconds: float = 20.0,
        refresh_delay_seconds: float = 8.0,
        failure_rate: float = 0.12,
        seed: int | None = None,
        now_factory=None,
    ) -> None:
        self._vin = vin
        self._nickname = nickname
        self._model = model
        self._capacity_kwh = capacity_kwh
        self._soh = state_of_health_percent
        self._idle_drain = idle_drain_percent_per_hour
        self._charge_rate = charge_percent_per_hour
        self._charging = charging
        self._plugged_in = plugged_in
        self._climate_spool = climate_spool_seconds
        self._refresh_delay = refresh_delay_seconds
        self._failure_rate = failure_rate
        self._random = random.Random(seed)
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

        started = self._now()
        self._anchor_soc = start_soc
        self._anchor_at = started
        # De auto praat uit zichzelf ongeveer elk half uur met Nissan.
        self._battery_updated_at = started - timedelta(minutes=42)
        self._climate_running = False
        self._climate_target: float | None = 21.0
        self._climate_started_at: datetime | None = None
        self._climate_updated_at = started - timedelta(minutes=42)
        #: Tijdstip waarop een aangevraagde verse meting bij Nissan binnenkomt.
        self._pending_refresh_at: datetime | None = None
        #: Forceer de slaapstand (voor tests van het foutpad).
        self.force_asleep = False

    # -- interne hulpjes ------------------------------------------------------

    def _now(self) -> datetime:
        return self._now_factory()

    def _soc(self) -> float:
        """Laadpercentage op dit moment, afgeleid van het verloop sinds het anker."""
        hours = (self._now() - self._anchor_at).total_seconds() / 3600.0
        rate = self._charge_rate if self._charging else -self._idle_drain
        return max(0.0, min(100.0, self._anchor_soc + rate * hours))

    def _maybe_asleep(self) -> None:
        """Simuleer een auto die niet reageert."""
        if self.force_asleep or self._random.random() < self._failure_rate:
            raise ApiError("vehicle_asleep")

    def _resolve_refresh(self) -> None:
        """Laat een aangevraagde verse meting pas zichtbaar worden als de auto zich meldt."""
        if self._pending_refresh_at is not None and self._now() >= self._pending_refresh_at:
            self._battery_updated_at = self._pending_refresh_at
            self._pending_refresh_at = None

    def _resolve_climate(self) -> None:
        """Laat een gestart klimaatcommando na de opstarttijd zichtbaar worden."""
        if (
            self._climate_started_at is not None
            and not self._climate_running
            and (self._now() - self._climate_started_at).total_seconds() >= self._climate_spool
        ):
            self._climate_running = True
            self._climate_updated_at = self._now()

    # -- publieke API ---------------------------------------------------------

    async def get_vehicle(self) -> VehicleInfo:
        return VehicleInfo(
            vin=self._vin,
            nickname=self._nickname,
            model=self._model,
            battery_capacity_kwh=self._capacity_kwh,
        )

    async def get_battery(self) -> BatteryState:
        self._resolve_refresh()
        soc = self._soc()
        # Klimaatregeling kost stroom; dat maakt de demo net wat geloofwaardiger.
        usable_range = DEFAULT_WLTP_RANGE_KM * (0.88 if self._climate_running else 1.0)
        return BatteryState(
            soc_percent=int(round(soc)),
            range_km=int(round(usable_range * soc / 100.0)),
            charging=self._charging,
            plugged_in=self._plugged_in,
            battery_capacity_kwh=self._capacity_kwh,
            state_of_health_percent=self._soh,
            updated_at=self._battery_updated_at,
            stale_minutes=compute_stale_minutes(self._battery_updated_at, self._now()),
        )

    async def request_battery_refresh(self) -> None:
        self._maybe_asleep()
        # De auto wordt wakker, meet, en meldt zich even later bij Nissan.
        self._anchor_soc = self._soc()
        self._anchor_at = self._now()
        self._pending_refresh_at = self._now() + timedelta(seconds=self._refresh_delay)

    async def get_climate(self) -> ClimateState:
        self._resolve_climate()
        return ClimateState(
            running=self._climate_running,
            target_temp_c=self._climate_target,
            updated_at=self._climate_updated_at,
        )

    async def start_climate(self, target_temp_c: float) -> None:
        self._maybe_asleep()
        # De echte auto kent alleen hele graden; de simulatie doet hetzelfde.
        self._climate_target = float(round(target_temp_c))
        self._climate_started_at = self._now()
        self._climate_updated_at = self._now()
        # `running` wordt pas true nadat `climate_spool_seconds` verstreken is.

    async def stop_climate(self) -> None:
        self._maybe_asleep()
        self._climate_running = False
        self._climate_started_at = None
        self._climate_updated_at = self._now()

    # -- alleen voor demo's en tests -----------------------------------------

    def set_charging(self, charging: bool) -> None:
        """Zet de gesimuleerde auto aan of van de lader."""
        self._anchor_soc = self._soc()
        self._anchor_at = self._now()
        self._charging = charging
        if charging:
            self._plugged_in = True
