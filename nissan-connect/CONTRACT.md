# Nissan Ariya Connect — interne API-contract

Dit bestand is de **enige bron van waarheid** voor de afspraak tussen backend en frontend.
Backend implementeert dit. Frontend consumeert dit. Wijzig dit bestand niet zonder overleg.

## Stack (vastgelegd)

- **Backend**: Python 3.11+, FastAPI, uvicorn. Draait op de Raspberry Pi / VPS / lokaal.
- **Frontend**: statische PWA — vanilla HTML/CSS/JS, geen build-stap (net als de rest van deze repo).
  Wordt door de backend zelf geserveerd op `/`.
- **Auth naar de app toe**: één gedeeld token (`APP_TOKEN` uit env), meegestuurd als
  `Authorization: Bearer <token>`. De frontend vraagt dit één keer en bewaart het in `localStorage`.
- **Nissan-credentials**: alléén server-side, uit environment variables / `.env`.
  NOOIT in de frontend, NOOIT in git.

## Endpoints

Alle responses zijn JSON. Alle fouten volgen het Error-schema hieronder.

### `GET /api/vehicle`
```json
{ "vin": "SJN...", "nickname": "Ariya", "model": "Ariya 87kWh", "battery_capacity_kwh": 87.0 }
```

### `GET /api/battery`
Levert de **gecachete** waarden zoals Nissan ze laatst van de auto kreeg. Snel (< 2s).
```json
{
  "soc_percent": 72,
  "range_km": 310,
  "charging": false,
  "plugged_in": true,
  "battery_capacity_kwh": 87.0,
  "state_of_health_percent": 98,
  "updated_at": "2026-09-13T08:14:00Z",
  "stale_minutes": 42
}
```
Velden die de auto niet levert zijn `null` — de frontend moet daar tegen kunnen.

### `POST /api/battery/refresh`
Vraagt de auto om een **verse** meting. Duurt lang (10–60s) en kan mislukken als de auto slaapt.
Async: geeft direct een job terug.
```json
{ "job_id": "abc123", "status": "pending" }
```

### `GET /api/jobs/{job_id}`
Pollen voor het resultaat van refresh of climate-commando's.
```json
{ "job_id": "abc123", "status": "pending|success|failed|timeout", "result": { }, "error": null }
```
Frontend pollt elke 3s, maximaal 90s.

### `GET /api/climate`
```json
{ "running": false, "target_temp_c": 21, "updated_at": "2026-09-13T08:14:00Z" }
```

### `POST /api/climate/start`
Body: `{ "target_temp_c": 21 }` — toegestaan bereik 16 t/m 26, HELE graden (de auto kent geen halve graden).
Antwoord: job-object, net als refresh.

### `POST /api/climate/stop`
Geen body. Antwoord: job-object.

## Error-schema

Elke fout, elke status ≥ 400:
```json
{ "error": { "code": "vehicle_asleep", "message": "De auto reageert niet — waarschijnlijk in slaapstand.", "retryable": true } }
```
Codes: `unauthorized`, `nissan_auth_failed`, `vehicle_asleep`, `rate_limited`,
`not_plugged_in`, `upstream_error`, `invalid_request`.
Berichten zijn **Nederlands** en gericht aan de eigenaar, niet aan een ontwikkelaar.

## Mock-modus

Met `MOCK=1` draait de backend zonder Nissan-account en geeft plausibele nepdata die
langzaam verandert (accu loopt leeg, opladen loopt op). Zo kan de frontend los ontwikkeld
en gedemonstreerd worden.

## Correcties na API-onderzoek (13-09-2026)

Zie `nissan-research/API-RESEARCH.md` voor de onderbouwing.

- **Temperatuur is in hele graden**, 16 t/m 26. Nissan accepteert geen halve graden.
- **Er is geen losse "zet temperatuur"-opdracht.** Temperatuur instellen en voorverwarmen
  starten zijn bij Nissan één actie (`hvac-start`). `GET /api/climate` geeft daarom de
  laatst gebruikte temperatuur terug, niet een apart opgeslagen instelling.
- **Timeouts moeten ruim zijn.** De Nissan-API doet er regelmatig meer dan een minuut over.
  Backend hanteert 120s HTTP-timeout; frontend pollt tot 120s.
- **Abonnement kan stilletjes verlopen.** Inloggen blijft dan werken en de auto is nog
  zichtbaar, alleen `services[]` meldt niet meer `ACTIVATED`. Backend controleert dit
  expliciet en geeft dan een duidelijke melding in plaats van een vage fout.

---

# Uitbreiding: alles wat de auto werkelijk teruggeeft (14-09-2026)

Onderstaande velden zijn **gemeten op de echte Ariya uit 2022**, niet aangenomen.
De ruwe waarden staan erbij, zodat de omrekening controleerbaar is.

## `GET /api/capabilities`

De interface mag niets tonen wat deze auto niet kan. Nissan geeft 403 op deuren,
laadschema, laadmodus en energie; een knop die altijd faalt is erger dan geen knop.
Dit endpoint zegt per onderdeel of het beschikbaar is. De backend bepaalt dit
één keer bij het eerste gebruik en onthoudt het.

```json
{
  "battery": true, "climate": true, "location": true,
  "odometer": true, "tyres": true, "doors": false, "charge_schedule": false
}
```

## `GET /api/battery` — uitgebreid

Bestaande velden blijven. Nieuw (ruwe Nissan-namen tussen haakjes):

```json
{
  "charging_remaining_minutes": 254,     // chargingRemainingTime
  "available_energy_kwh": 22,            // batteryAvailableEnergy
  "battery_temperature_c": null          // batteryTemperature; gaf 0 op een ladende auto,
                                         // dus waarschijnlijk niet ondersteund. Bij 0 -> null.
}
```

## `GET /api/climate` — uitgebreid

```json
{ "internal_temperature_c": 16.0 }       // internalTemperature: de gemeten
                                         // binnentemperatuur, niet de streeftemperatuur
```

Let op: `target_temp_c` (wat je wilt) en `internal_temperature_c` (wat het nú is)
zijn verschillende dingen. De interface moet dat onderscheid duidelijk maken.

## `GET /api/location`

```json
{
  "latitude": 51.675196944444444,
  "longitude": 5.042029166666667,
  "heading_degrees": 298.0,
  "updated_at": "2026-09-14T07:05:26Z",
  "stale_minutes": 4
}
```

Geen kaartdienst van buitenaf aanroepen: de pagina mag geen enkel extern verzoek
doen. Toon de coördinaten, een kompasrichting, en een link naar een kaart die de
gebruiker zelf aanklikt.

## `GET /api/odometer`

```json
{ "total_km": 21126, "updated_at": null }   // totalMileage
```

## `GET /api/tyres`

Nissan levert per wiel een druk en een status. Ruwe waarden: `flPressure: 2070`.
Gedeeld door 1000 geeft 2,07 bar, wat klopt voor een personenauto.
**Die omrekening is aangenomen, niet bevestigd** — zet dat in een opmerking bij de code.
`status: 0` betekende bij alle vier de wielen in orde.

```json
{
  "front_left":  { "bar": 2.07, "ok": true },
  "front_right": { "bar": 2.01, "ok": true },
  "rear_left":   { "bar": 2.16, "ok": true },
  "rear_right":  { "bar": 2.10, "ok": true },
  "updated_at": null
}
```

## Niet beschikbaar op deze auto

Deuren vergrendelen, laadschema, laadmodus, energiekosten: Nissan antwoordt 403.
De ritgeschiedenis gaf 400 en onderhoud 404. Niet inbouwen tot een meting het
tegendeel laat zien.
