"""Verken wat jouw Nissan werkelijk aanbiedt.

Dit script logt in met de gegevens uit `.env`, vraagt op welke diensten er op
jouw auto actief zijn, en tast daarna af welke gegevens daadwerkelijk op te
halen zijn.

VEILIG: er worden uitsluitend GET-verzoeken gedaan naar gegevens die Nissan al
in de cloud heeft staan. De auto wordt niet wakker gemaakt en er wordt niets
aan- of uitgezet. Je 12V-accu loopt hier dus geen risico.

Gebruik:
    .\\.venv\\Scripts\\python.exe ontdek.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.config import get_settings
from app.errors import ApiError
from app.vehicle.kamereon import KamereonVehicleClient

#: Betekenis van de dienst-ID's die Nissan meestuurt. Wat hier niet in staat,
#: wordt gewoon als onbekend getoond -- liever eerlijk dan verzonnen.
DIENSTEN: dict[str, str] = {
    "300": "Voertuiggegevens",
    "301": "Locatie van de auto",
    "302": "Deuren en sloten",
    "303": "Claxon en lichten",
    "305": "Ritgeschiedenis",
    "307": "Interieurtemperatuur instellen",
    "308": "Laadschema",
    "309": "Meldingen",
    "310": "Kilometerstand",
    "311": "Onderhoudsinformatie",
    "312": "Bandenspanning",
    "319": "Accustatus",
    "323": "Accugezondheid",
    "366": "Voorverwarmen aan/uit",
    "401": "Alarmmeldingen",
    "2042": "Temperatuurinstelling",
}

#: Alleen-lezen adressen om af te tasten. {vin} wordt ingevuld.
PROEVEN: list[tuple[str, str, str]] = [
    ("Accustatus (bff-web v3)", "user", "v3/cars/{vin}/battery-status"),
    ("Accustatus (car-adapter v1)", "car", "v1/cars/{vin}/battery-status"),
    ("Klimaat", "car", "v1/cars/{vin}/hvac-status"),
    ("Locatie", "car", "v1/cars/{vin}/location"),
    ("Kilometerstand", "car", "v1/cars/{vin}/cockpit"),
    ("Deuren en sloten", "car", "v1/cars/{vin}/lock-status"),
    ("Bandenspanning", "car", "v1/cars/{vin}/pressure"),
    ("Laadschema", "car", "v1/cars/{vin}/charging-settings"),
    ("Laadmodus", "car", "v1/cars/{vin}/charge-mode"),
    ("Energie-overzicht", "car", "v1/cars/{vin}/energy-unit-cost"),
    ("Ritten deze maand", "car", "v1/cars/{vin}/trip-history"),
    ("Onderhoud", "user", "v2/cars/{vin}/maintenance"),
    ("Meldingen", "user", "v1/cars/{vin}/notifications"),
]


def _kort(waarde: Any, lengte: int = 300) -> str:
    tekst = json.dumps(waarde, ensure_ascii=False)
    return tekst if len(tekst) <= lengte else tekst[:lengte] + " ..."


async def main() -> None:
    instellingen = get_settings()
    if instellingen.mock:
        print("MOCK staat nog op 1. Zet MOCK=0 in .env om je echte auto te bevragen.")
        return

    client = KamereonVehicleClient(
        username=instellingen.nissan_username,
        password=instellingen.nissan_password,
        region=instellingen.nissan_region,
    )

    try:
        auto = await client._get_vehicle_data()
        vin = str(auto.get("vin", "")).upper()

        print("=" * 70)
        print(f"  {auto.get('modelName', '?')} {auto.get('modelYear', '')}"
              f"  ({auto.get('nickname') or 'geen naam'})")
        print(f"  VIN eindigt op ...{vin[-6:]}")
        print("=" * 70)

        print("\nDIENSTEN OP JOUW ABONNEMENT\n")
        diensten = auto.get("services") or []
        if not diensten:
            print("  (Nissan stuurde geen dienstenlijst mee.)")
        for dienst in sorted(diensten, key=lambda d: str(d.get("id"))):
            ident = str(dienst.get("id"))
            staat = dienst.get("activationState", "?")
            merk = "AAN " if staat == "ACTIVATED" else "uit "
            naam = DIENSTEN.get(ident, "onbekende dienst")
            print(f"  [{merk}] {ident:>5}  {naam}")

        print("\n\nWAT IS ER ECHT OP TE HALEN\n")
        for omschrijving, host, pad in PROEVEN:
            basis = (
                client._settings["user_base_url"]
                if host == "user"
                else client._settings["car_adapter_base_url"]
            )
            url = basis + pad.format(vin=vin)
            try:
                body = await client._request("GET", url)
            except ApiError as exc:
                print(f"  [nee] {omschrijving:<30} {exc.code}")
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"  [nee] {omschrijving:<30} {type(exc).__name__}")
                continue

            gegevens = (body.get("data") or {}).get("attributes") or body.get("attributes") or body
            print(f"  [JA ] {omschrijving:<30} {_kort(gegevens)}")

        print("\nKlaar. Regels met [JA] zijn gegevens die we in de app kunnen tonen.")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
