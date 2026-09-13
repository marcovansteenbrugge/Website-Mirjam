# Nissan Ariya Connect — backend

Kleine persoonlijke backend om **je eigen** Nissan Ariya uit te lezen (accustand)
en voor te verwarmen, vanaf je telefoon of laptop. Python 3.11+, FastAPI.

De afspraak met de webpagina staat in [`../CONTRACT.md`](../CONTRACT.md). Dat
bestand is leidend; deze server implementeert het.

---

## Snel starten (mock-modus — zonder auto en zonder Nissan-account)

Zo draait alles met een nagebootste Ariya. Handig om de webpagina te bouwen of
gewoon even rond te kijken.

```bash
cd nissan-connect/server

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Zet in .env een APP_TOKEN van minimaal 16 tekens:
python -c "import secrets; print(secrets.token_urlsafe(32))"
# en laat MOCK=1 staan

uvicorn app.main:app --reload --port 8000
```

Open daarna <http://localhost:8000/>. De webpagina vraagt één keer om je
`APP_TOKEN` en onthoudt dat in de browser.

Even snel testen zonder browser:

```bash
curl -H "Authorization: Bearer <jouw APP_TOKEN>" http://localhost:8000/api/battery
```

De nagebootste auto gedraagt zich als een echte: de accu loopt langzaam leeg,
loopt op tijdens laden, voorverwarmen heeft ongeveer 20 seconden nodig voordat
hij "aan" meldt, en af en toe reageert de auto niet (`vehicle_asleep`). Dat
laatste is expres — zo test je ook meteen de foutmeldingen.

---

## Echte modus (je eigen Ariya)

```bash
# in .env:
MOCK=0
NISSAN_USERNAME=jouw-nissan-e-mailadres
NISSAN_PASSWORD=jouw-nissan-wachtwoord
NISSAN_REGION=NL
APP_TOKEN=<lang willekeurig token>

uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Je Nissan-gegevens blijven op de server. Ze gaan nooit naar de browser en komen
nooit in een logregel terecht (zie `app/redaction.py`).

**Zet dit niet zomaar open op internet.** Gebruik een reverse proxy met HTTPS
(Caddy, nginx) of houd het binnen je eigen netwerk / VPN. Het `APP_TOKEN` is de
enige sleutel tussen de buitenwereld en een auto die kan gaan draaien.

### Waarschuwing vooraf

De echte client (`app/vehicle/kamereon.py`) is gebouwd op de endpoints van de
onderhouden Home Assistant-integratie voor NissanConnect EU en is **niet tegen
een echte auto getest** (daar zijn echte inloggegevens voor nodig). Twee dingen
weigert hij bewust in plaats van te gokken:

* **halve graden** als streeftemperatuur (21.5 °C) — alle bronnen sturen een
  heel getal 16..26; kies dus 21 of 22;
* **regio's buiten Europa** — die instellingen staan nergens in broncode.

In beide gevallen krijg je een duidelijke foutmelding, geen stilzwijgend
verkeerd commando naar je auto. `state_of_health_percent` (accugezondheid) is
altijd `null`: Nissan levert dat veld niet in de gebruikte API.

---

## Waarom er een rem op "verse meting" zit

`POST /api/battery/refresh` maakt de auto **echt wakker**. Dat kost stroom uit de
kleine 12V-startaccu. Een EV die veel stilstaat en steeds wakker gepord wordt,
kan een lege 12V-accu krijgen — en dan doet de auto helemaal niets meer, ook de
laadklep niet.

Daarom staat er standaard minimaal **15 minuten** tussen twee verse metingen
(`POLL_MIN_INTERVAL_SECONDS`). Vraag je er eerder een, dan krijg je netjes een
`rate_limited`-fout met hoeveel minuten je nog moet wachten.

Het gewone uitlezen, `GET /api/battery`, valt hier **niet** onder: dat leest
alleen wat Nissan al in de cloud heeft staan en raakt de auto niet aan. Daar mag
de webpagina zo vaak om vragen als hij wil.

Loopt er al een verse meting? Dan levert een tweede verzoek gewoon diezelfde
opdracht (hetzelfde `job_id`) op — er gaat nooit een tweede commando naar de auto.

---

## Endpoints

Alle endpoints vragen `Authorization: Bearer <APP_TOKEN>`.

| Methode | Pad | Wat het doet |
|---|---|---|
| `GET` | `/api/vehicle` | VIN, naam, model, accucapaciteit |
| `GET` | `/api/battery` | Laatst bekende accustand (snel, raakt de auto niet aan) |
| `POST` | `/api/battery/refresh` | Vraagt een verse meting → geeft een opdracht terug |
| `GET` | `/api/jobs/{job_id}` | Status van een opdracht: `pending`/`success`/`failed`/`timeout` |
| `GET` | `/api/climate` | Draait de klimaatregeling? |
| `POST` | `/api/climate/start` | Voorverwarmen, body `{"target_temp_c": 21.0}` (16.0–26.0) |
| `POST` | `/api/climate/stop` | Klimaatregeling uit |

Lange opdrachten (verse meting, voorverwarmen) duren 10–60 seconden. Die geven
meteen een `job_id` terug; de webpagina pollt daarna `/api/jobs/{job_id}`.

Elke fout ziet er hetzelfde uit:

```json
{ "error": { "code": "vehicle_asleep",
             "message": "De auto reageert niet — waarschijnlijk in slaapstand.",
             "retryable": true } }
```

Interactieve documentatie draait op <http://localhost:8000/docs>.

---

## Tests

```bash
cd nissan-connect/server
./.venv/bin/python -m pytest
```

De tests draaien volledig tegen de nagebootste auto — geen Nissan-account,
geen internet. Ze dekken de toegangscontrole, alle endpoints, de levensloop van
een opdracht, de rem op verse metingen en de vorm van elke foutmelding.

---

## Opbouw

```
server/
├── app/
│   ├── main.py          FastAPI-app: endpoints + statische frontend op /
│   ├── auth.py          Bearer-token-controle (constante-tijdvergelijking)
│   ├── config.py        Instellingen uit .env / environment
│   ├── errors.py        Het foutschema uit het contract
│   ├── jobs.py          Opdrachten in het geheugen + de 12V-rem
│   ├── redaction.py     Houdt wachtwoorden en tokens uit de logs
│   └── vehicle/
│       ├── base.py      De interface waar al het andere op leunt
│       ├── mock.py      Nagebootste Ariya (MOCK=1)
│       └── kamereon.py  De echte NissanConnect-client
└── tests/
```

`app/vehicle/base.py` is het scharnierpunt: de rest van de applicatie kent
alléén die interface. Of er nu een echte auto of een simulatie achter hangt,
maakt voor `main.py` niets uit.
