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
{ "running": false, "target_temp_c": 21.0, "updated_at": "2026-09-13T08:14:00Z" }
```

### `POST /api/climate/start`
Body: `{ "target_temp_c": 21.0 }` — toegestaan bereik 16.0 t/m 26.0, stappen van 0.5.
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
