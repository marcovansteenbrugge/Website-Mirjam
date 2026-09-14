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

import math
import random
from datetime import datetime, timedelta, timezone

from ..errors import ApiError
from .base import (
    BatteryState,
    Capabilities,
    CapabilityCache,
    ClimateState,
    LocationState,
    OdometerState,
    TyrePressure,
    TyreState,
    VehicleClient,
    VehicleInfo,
    compute_stale_minutes,
)

#: Plausibele Ariya 87 kWh.
DEFAULT_CAPACITY_KWH = 87.0
DEFAULT_WLTP_RANGE_KM = 500.0

#: Startpunt van de gesimuleerde auto: een parkeerplaats in Noord-Brabant,
#: dezelfde hoek als de meting op de echte auto.
DEFAULT_LATITUDE = 51.675196944444444
DEFAULT_LONGITUDE = 5.042029166666667
DEFAULT_HEADING_DEGREES = 298.0

#: Kilometerstand bij het opstarten van de simulatie, en hoe hard hij oploopt.
#: 3 km per uur klinkt weinig, maar het is een *gemiddelde* over dag en nacht:
#: ongeveer 70 km per etmaal, wat een normale dagelijkse auto is.
DEFAULT_ODOMETER_KM = 21126.0
ODOMETER_KM_PER_HOUR = 3.0

#: Koude bandenspanning per wiel (bar), zoals op de echte auto gemeten.
DEFAULT_TYRE_BAR: dict[str, float] = {
    "front_left": 2.07,
    "front_right": 2.01,
    "rear_left": 2.16,
    "rear_right": 2.10,
}
#: Hoeveel de spanning in de simulatie heen en weer wandelt (bar). Echte banden
#: doen dit ook: warmer weer of een rit erop en de druk loopt een paar honderdste op.
TYRE_DRIFT_BAR = 0.05

#: Wat de mock-auto kan. Deuren en laadschema staan op `False` omdat de échte
#: Ariya daar 403 op geeft. De mock hoort geen mogelijkheden voor te spiegelen
#: die de eigenaar in zijn eigen auto niet heeft -- anders bouwt de frontend een
#: knop die alleen in de demo werkt.
MOCK_CAPABILITIES: dict[str, bool] = {
    "battery": True,
    "climate": True,
    "location": True,
    "odometer": True,
    "tyres": True,
    "doors": False,
    "charge_schedule": False,
}


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
        latitude: float = DEFAULT_LATITUDE,
        longitude: float = DEFAULT_LONGITUDE,
        heading_degrees: float = DEFAULT_HEADING_DEGREES,
        odometer_km: float = DEFAULT_ODOMETER_KM,
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
        self._latitude = latitude
        self._longitude = longitude
        self._heading = heading_degrees
        self._odometer_start_km = odometer_km
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
        #: De auto meldde locatie, kilometerstand en banden het laatst toen hij
        #: ook de accustand doorgaf.
        self._location_updated_at = started - timedelta(minutes=4)
        self._odometer_at = started
        #: Net als bij de echte auto liggen deze vast: gemeten, niet geraden.
        self._capabilities = CapabilityCache(MOCK_CAPABILITIES)

    # -- interne hulpjes ------------------------------------------------------

    def _now(self) -> datetime:
        return self._now_factory()

    def _soc(self) -> float:
        """Laadpercentage op dit moment, afgeleid van het verloop sinds het anker."""
        hours = (self._now() - self._anchor_at).total_seconds() / 3600.0
        rate = self._charge_rate if self._charging else -self._idle_drain
        return max(0.0, min(100.0, self._anchor_soc + rate * hours))

    def _hours_since_start(self) -> float:
        return max(0.0, (self._now() - self._odometer_at).total_seconds() / 3600.0)

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
        # Resterende laadtijd: alleen zinvol als hij ook echt laadt.
        remaining = None
        if self._charging and self._charge_rate > 0:
            remaining = int(round((100.0 - soc) / self._charge_rate * 60.0))
        return BatteryState(
            soc_percent=int(round(soc)),
            range_km=int(round(usable_range * soc / 100.0)),
            charging=self._charging,
            plugged_in=self._plugged_in,
            battery_capacity_kwh=self._capacity_kwh,
            state_of_health_percent=self._soh,
            charging_remaining_minutes=remaining,
            available_energy_kwh=round(self._capacity_kwh * soc / 100.0, 1),
            # De echte auto geeft hier 0 terug, wat "niet ondersteund" betekent
            # en door de Kamereon-client naar `None` wordt vertaald. De mock
            # doet hetzelfde, zodat de frontend het lege geval ook echt oefent.
            battery_temperature_c=None,
            updated_at=self._battery_updated_at,
            stale_minutes=compute_stale_minutes(self._battery_updated_at, self._now()),
        )

    async def request_battery_refresh(self) -> None:
        self._maybe_asleep()
        # De auto wordt wakker, meet, en meldt zich even later bij Nissan.
        self._anchor_soc = self._soc()
        self._anchor_at = self._now()
        self._pending_refresh_at = self._now() + timedelta(seconds=self._refresh_delay)

    def _internal_temperature(self) -> float:
        """Gemeten binnentemperatuur -- iets anders dan de streeftemperatuur.

        Staat de klimaatregeling uit, dan koelt het interieur naar een kille
        16 graden (de waarde die op de echte auto gemeten is). Draait hij, dan
        kruipt de temperatuur langzaam naar de streefwaarde toe, zonder die ooit
        precies te halen; zo blijven "wat je wilt" en "wat het is" zichtbaar
        verschillend.
        """
        koud = 16.0
        if not self._climate_running or self._climate_started_at is None:
            return koud
        doel = self._climate_target or 21.0
        minuten = max(0.0, (self._now() - self._climate_started_at).total_seconds() / 60.0)
        aandeel = 1.0 - math.exp(-minuten / 12.0)
        return round(koud + (doel - koud) * aandeel * 0.9, 1)

    async def get_climate(self) -> ClimateState:
        self._resolve_climate()
        return ClimateState(
            running=self._climate_running,
            target_temp_c=self._climate_target,
            internal_temperature_c=self._internal_temperature(),
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

    async def get_location(self) -> LocationState:
        """Een auto die op de oprit staat: de positie blijft waar hij is."""
        return LocationState(
            latitude=self._latitude,
            longitude=self._longitude,
            heading_degrees=self._heading,
            updated_at=self._location_updated_at,
            stale_minutes=compute_stale_minutes(self._location_updated_at, self._now()),
        )

    async def get_odometer(self) -> OdometerState:
        """Kilometerstand die langzaam oploopt met de verstreken tijd."""
        total = self._odometer_start_km + ODOMETER_KM_PER_HOUR * self._hours_since_start()
        return OdometerState(
            total_km=int(total),
            # Net als de echte auto: geen tijdstempel bij de kilometerstand.
            updated_at=None,
        )

    def _tyre(self, wiel: str, fase: float) -> TyrePressure:
        """Bandenspanning die langzaam heen en weer wandelt rond de koude druk."""
        uren = self._hours_since_start()
        basis = DEFAULT_TYRE_BAR[wiel]
        druk = basis + TYRE_DRIFT_BAR * math.sin(uren / 5.0 + fase)
        return TyrePressure(bar=round(druk, 2), ok=druk >= 1.8)

    async def get_tyres(self) -> TyreState:
        return TyreState(
            front_left=self._tyre("front_left", 0.0),
            front_right=self._tyre("front_right", 1.3),
            rear_left=self._tyre("rear_left", 2.6),
            rear_right=self._tyre("rear_right", 3.9),
            updated_at=None,
        )

    async def get_capabilities(self) -> Capabilities:
        """Precies wat de echte auto teruggaf: deuren en laadschema kunnen niet."""
        return Capabilities(**self._capabilities.snapshot())

    # -- alleen voor demo's en tests -----------------------------------------

    def set_charging(self, charging: bool) -> None:
        """Zet de gesimuleerde auto aan of van de lader."""
        self._anchor_soc = self._soc()
        self._anchor_at = self._now()
        self._charging = charging
        if charging:
            self._plugged_in = True
