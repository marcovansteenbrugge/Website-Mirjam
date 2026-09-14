# Ariya — accu & voorverwarmen

Een eigen app om de accu van de Nissan Ariya uit te lezen en de auto voor te
verwarmen, zonder de officiële NissanConnect-app.

```
nissan-connect/
├── CONTRACT.md    De afspraak tussen server en webpagina
├── server/        De backend (Python/FastAPI) — praat met Nissan
└── web/           De webpagina — wat je op je telefoon ziet
```

## Eerst proberen zonder je Nissan-account

Zo zie je of de bediening bevalt, zonder dat er iets naar je auto gaat.

```bash
cd nissan-connect/server
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

cp .env.example .env
# Zet in .env een APP_TOKEN (minimaal 16 tekens) en laat MOCK=1 staan.
# Een token maken:  python3 -c "import secrets; print(secrets.token_urlsafe(32))"

./.venv/bin/python -m uvicorn app.main:app --port 8000
```

Open daarna http://localhost:8000 en vul het token in dat je in `.env` zette.
Je ziet een nagebootste Ariya: de accu loopt langzaam leeg, opladen werkt,
voorverwarmen duurt zoals in het echt een halve minuut.

## Snelkoppeling op je bureaublad

Eenmalig, vanuit de map `nissan-connect`:

```powershell
powershell -ExecutionPolicy Bypass -File .\maak-snelkoppeling.ps1
```

Daarna staat er een snelkoppeling **Ariya** op je bureaublad. Dubbelklikken
start de server en opent de pagina zodra die klaar is — niet eerder, want een
te vroeg geopende pagina toont een foutmelding die eruitziet alsof er iets stuk is.

Draait de server al, dan opent de snelkoppeling alleen de pagina in plaats van
een tweede server te starten.

Het venster dat daarbij hoort houdt de server draaiend. **Sluit je dat venster,
dan stopt de app.** Dat is bewust: zo is altijd zichtbaar of hij aanstaat.

## Daarna met de echte auto

Zet in `.env`:

```
MOCK=0
NISSAN_USERNAME=je@email.nl
NISSAN_PASSWORD=je-wachtwoord
```

Dat zijn dezelfde gegevens als waarmee je in de officiële Nissan-app inlogt.
`.env` staat in `.gitignore` en gaat dus nooit mee naar GitHub.

**Dit is het moment van de waarheid.** Alles hierboven is getest tegen een
nagebootste auto; tegen een echte Nissan-server is nog niets bevestigd.

Werkt het niet, kijk dan eerst naar de foutmelding — die is met opzet specifiek:

| Melding gaat over | Wat er waarschijnlijk aan de hand is |
|---|---|
| Verlopen abonnement | Je NissanConnect-abonnement is afgelopen. Inloggen blijft dan gewoon werken, alleen de diensten niet. |
| Inloggegevens geweigerd | Wachtwoord klopt niet. De app probeert het met opzet **niet** nog een keer, want Nissan vergrendelt accounts. |
| Auto reageert niet | De auto slaapt of heeft geen bereik. Gewoon later opnieuw proberen. |
| Openstaande melding in de app | Open de officiële Nissan-app en accepteer wat daar klaarstaat (voorwaarden of toestemming). |

## Twee dingen om te weten

**Verversen maakt de auto echt wakker.** Daarom zit er een rem op van 15 minuten.
Te vaak wakker maken trekt de 12V-accu leeg, en dan doet de auto helemaal niets
meer. Het gewone uitlezen valt hier niet onder: dat leest alleen wat Nissan al
weet en raakt de auto niet aan.

**Temperatuur en voorverwarmen zijn één handeling.** Nissan kent geen losse
"zet de temperatuur"-opdracht. Je kiest een temperatuur en drukt op starten.
Wil je 'm tijdens het voorverwarmen wijzigen, dan moet je opnieuw starten.
Alleen hele graden, 16 tot 26.

## Accugezondheid

Die blijft leeg. Nissan geeft de fabriekscapaciteit terug, niet de slijtage, en
die twee door elkaar halen geeft een getal dat iets anders betekent dan je denkt.
Wil je echte accugezondheid, dan heb je een OBD-II-dongle in de auto nodig.

## Onderhoud

Het Nissan-platform veranderde in 2026 twee keer: in maart ging het oude
Carwings uit, eind augustus kwam er een nieuw inlogsysteem. Breekt het weer,
dan zitten alle Nissan-adressen en -sleutels bij elkaar bovenin
`server/app/vehicle/kamereon.py`. Zie `../nissan-research/API-RESEARCH.md`
voor hoe het in elkaar zit.
