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
