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

De echte client (`app/vehicle/kamereon.py`) volgt de inlogroute en de endpoints
van de onderhouden Home Assistant-integratie voor NissanConnect EU, aangevuld met
het onderzoeksrapport in `../../nissan-research/API-RESEARCH.md`. Twee
onafhankelijke implementaties zijn het over alle constanten eens — maar er is
**niets tegen een echte Nissan-server getest**, want daar zijn echte
inloggegevens en een echte auto voor nodig.

Wat de backend bewust weigert in plaats van te gokken:

* **halve graden** als streeftemperatuur. De auto kent alleen hele graden van
  16 t/m 26. Kies dus 21 of 22, niet 21,5. Er bestaat ook geen aparte "zet
  temperatuur"-opdracht: de temperatuur hoort bij het *starten*. Wil je hem
  wijzigen terwijl het voorverwarmen draait, dan start je opnieuw.
* **regio's buiten Europa** — die instellingen staan nergens in broncode.

`state_of_health_percent` (accugezondheid) is altijd `null`: Nissan levert dat
veld niet in deze API. Wie de echte accugezondheid wil weten, heeft een
OBD-II-dongle nodig.

### Als het niet werkt, kijk hier eerst

* **Abonnement verlopen.** Dit is de meest waarschijnlijke oorzaak. Je kunt dan
  nog gewoon inloggen en de auto staat er nog gewoon in — alleen doet niets het
  meer. De backend herkent dit en zegt het met zoveel woorden.
* **Auto niet gekoppeld.** De auto moet al in de MyNISSAN-app staan; via deze
  weg koppelen kan niet.
* **Inloggen loopt vast.** Meestal wacht er een akkoordverklaring of verificatie
  in de MyNISSAN-app zelf. De backend probeert een afgewezen inlogpoging
  **niet** opnieuw: Nissan kan je account bij herhaalde pogingen blokkeren.
* **Traag is normaal.** De API is echt traag; de HTTP-timeout staat daarom op
  120 seconden. Een verse meting die niet lukt omdat de auto slaapt, is geen
  storing maar gewoon het normale geval.

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
| `POST` | `/api/climate/start` | Voorverwarmen, body `{"target_temp_c": 21.0}` (16–26, hele graden) |
| `POST` | `/api/climate/stop` | Klimaatregeling uit |
| `GET` | `/api/location` | Laatst bekende positie: breedte, lengte, kompasrichting |
| `GET` | `/api/odometer` | Kilometerstand |
| `GET` | `/api/tyres` | Bandenspanning per wiel, in bar |
| `GET` | `/api/capabilities` | Wat deze auto werkelijk ondersteunt |

`location`, `odometer` en `tyres` lezen — net als `battery` — alleen wat Nissan
al in de cloud heeft staan. Ze maken de auto niet wakker.

### Wat kan deze auto eigenlijk?

`GET /api/capabilities` zegt per onderdeel of het beschikbaar is. Dat staat
nergens in een lijstje in de code: de backend probeert elk onderdeel één keer
écht en onthoudt het antwoord. Lukt het, dan `true`; antwoordt Nissan met 403 of
404, dan `false` en wordt het die sessie niet meer gevraagd. Zo klopt het ook op
een andere auto of met een ander abonnement, en kost een paginaweergave geen
reeks verzoeken waarvan het antwoord al bekend is.

Op de Ariya uit 2022 geven deuren, laadschema, laadmodus en energie 403. Een
verzoek aan zo'n onderdeel levert daarom geen "er ging iets mis", maar status
501 met de uitleg dat deze auto dit niet ondersteunt. De mock-auto doet hier
precies hetzelfde, zodat de frontend dat geval ook in de demo tegenkomt.

### Twee aannames die je moet kennen

- **Bandenspanning.** De auto geeft `flPressure: 2070`. Gedeeld door 1000 is dat
  2,07 bar, wat klopt voor een personenauto — maar de eenheid is nergens
  bevestigd. Klopt de weergave niet met je bandenpompmeter, kijk dan bij
  `RAW_PRESSURE_PER_BAR` in `app/vehicle/kamereon.py`.
- **Accutemperatuur.** `batteryTemperature` gaf 0 terwijl de auto stond te laden.
  Een ladende accu is nooit precies 0 graden, dus dat is vrijwel zeker een
  niet-ingevuld veld. De backend maakt er `null` van in plaats van "het
  vriespunt" te tonen.

Lange opdrachten (verse meting, voorverwarmen) duren 10–60 seconden. Die geven
meteen een `job_id` terug; de webpagina pollt daarna `/api/jobs/{job_id}`.

> **Afwijking van `CONTRACT.md`:** het contract noemt temperatuurstappen van een
> halve graad. De auto kent die niet — Nissan accepteert alleen hele graden van
> 16 t/m 26. De backend valideert daarop en weigert 21,5 met `invalid_request`.
> Het contract en de frontend worden hierop aangepast.

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

De tests draaien volledig zonder Nissan-account en zonder internet. Ze dekken:

* de toegangscontrole en alle endpoints tegen de nagebootste auto;
* de levensloop van een opdracht (inclusief mislukken en verlopen);
* de rem op verse metingen;
* de vorm van elke foutmelding volgens het contract;
* en van de échte client: de opgebouwde URL's, query-parameters en bodies,
  tegen een nagebootste HTTP-laag (`httpx.MockTransport`).

Wat de tests **niet** kunnen bewijzen: dat Nissan die verzoeken ook accepteert.
Daar is een echt account voor nodig.

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
