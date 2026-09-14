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

#: Betekenis van de dienst-ID's die Nissan meestuurt.
#:
#: LET OP -- dit is grotendeels GISWERK en blijkt aantoonbaar onbetrouwbaar.
#: Op een echte Ariya staat 308 op ACTIVATED terwijl het laadschema-adres 403
#: teruggeeft, en 311 staat aan terwijl onderhoud 404 geeft. Omgekeerd werkt de
#: locatie prima terwijl het nummer dat daarbij zou horen niet eens in de lijst
#: voorkomt. Vertrouw dus de metingen in het onderste deel van dit script, niet
#: deze tabel.
#:
#: Alleen deze vier zijn bevestigd doordat het bijbehorende adres ook echt
#: gegevens teruggaf:
DIENSTEN: dict[str, str] = {
    "319": "Accustatus (bevestigd)",
    "366": "Voorverwarmen aan/uit (bevestigd)",
    "312": "Bandenspanning (bevestigd)",
    "2042": "Temperatuurinstelling (bevestigd)",
    # Hieronder: vermoedens uit oudere bronnen, NIET bevestigd op deze auto.
    "301": "Locatie?",
    "302": "Deuren en sloten?",
    "303": "Claxon en lichten?",
    "305": "Ritgeschiedenis?",
    "307": "Interieurtemperatuur?",
    "308": "Laadschema? (adres gaf 403)",
    "310": "Kilometerstand?",
    "311": "Onderhoud? (adres gaf 404)",
    "323": "Accugezondheid?",
}


#: Alleen-lezen adressen om af te tasten: (omschrijving, host, pad, params).
#: Host is "user" (bff-web), "car" (car-adapter) of "notif" (notifications).
#:
#: Waarom meerdere varianten van hetzelfde: bij de accustand bleek de bff-web-
#: route voor de Ariya rijkere gegevens te geven dan de car-adapter, terwijl
#: beide bestaan. Welke route bij welk gegeven hoort is nergens vastgelegd, dus
#: wordt het gemeten in plaats van aangenomen.
PROEVEN: list[tuple[str, str, str, dict[str, str]]] = [
    ("Accustatus (bff-web v3)", "user", "v3/cars/{vin}/battery-status", {}),
    ("Accustatus (car-adapter v1)", "car", "v1/cars/{vin}/battery-status", {}),
    ("Klimaat", "car", "v1/cars/{vin}/hvac-status", {}),
    ("Locatie", "car", "v1/cars/{vin}/location", {}),
    ("Kilometerstand", "car", "v1/cars/{vin}/cockpit", {}),
    ("Bandenspanning", "car", "v1/cars/{vin}/pressure", {}),

    # --- Deuren en sloten: drie routes, want de car-adapter gaf 403 ---------
    ("Deuren (car-adapter v1)", "car", "v1/cars/{vin}/lock-status", {}),
    ("Deuren (car-adapter v2)", "car", "v2/cars/{vin}/lock-status", {}),
    ("Deuren (bff-web v1)", "user", "v1/cars/{vin}/lock-status", {}),
    ("Deuren (bff-web v3)", "user", "v3/cars/{vin}/lock-status", {}),

    # --- Laden: dienst 308 staat AAN, dus ergens moet dit te halen zijn -----
    ("Laadschema (car-adapter)", "car", "v1/cars/{vin}/charging-settings", {}),
    ("Laadschema (bff-web v1)", "user", "v1/cars/{vin}/charging-settings", {}),
    ("Laadschema (bff-web v2)", "user", "v2/cars/{vin}/charging-settings", {}),
    ("Laadmodus (bff-web)", "user", "v1/cars/{vin}/charge-mode", {}),

    # --- Meldingen: eerder op de verkeerde host geprobeerd ------------------
    ("Meldingen (eigen host)", "notif", "v2/{vin}/notifications", {}),
    ("Meldingen (eigen host v1)", "notif", "v1/{vin}/notifications", {}),

    # --- Onderhoud en ritten -----------------------------------------------
    ("Onderhoud (bff-web v1)", "user", "v1/cars/{vin}/maintenance", {}),
    ("Voertuigdetails", "user", "v5/cars/{vin}", {}),
    (
        "Ritten (met datums)",
        "car",
        "v1/cars/{vin}/trip-history",
        {"type": "monthly", "start": "2026-08", "end": "2026-09"},
    ),
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
        hosts = {
            "user": client._settings["user_base_url"],
            "car": client._settings["car_adapter_base_url"],
            "notif": client._settings["notifications_base_url"],
        }
        for omschrijving, host, pad, params in PROEVEN:
            url = hosts[host] + pad.format(vin=vin)
            try:
                body = await client._request("GET", url, params=params or None)
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
