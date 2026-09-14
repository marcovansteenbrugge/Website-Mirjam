# Logboek — een eigen app voor de Nissan Ariya

Wat er gebouwd is, wat we onderweg ontdekten, en waarom bepaalde keuzes zo
uitpakten. Geschreven voor wie hier over een half jaar weer in duikt.

Gebouwd op 13 en 14 september 2026, voor een Nissan Ariya uit 2022 (VIN eindigt
op 207630), NissanConnect-abonnement lopend tot 2031.

---

## Waar het om begonnen was

De officiële NissanConnect-app deed het niet. Doel: zelf de accu kunnen uitlezen
en de auto kunnen voorverwarmen.

Dat werkt nu allebei, plus locatie, kilometerstand en bandenspanning.

---

## De belangrijkste ontdekking: bijna alles wat online staat, klopt niet meer

Het Nissan-platform veranderde in 2026 **twee keer**. Wie een blogpost of README
van vóór september 2026 volgt, bouwt tegen een dode API.

| Wanneer | Wat er gebeurde |
|---|---|
| 30 maart 2026 | Het oude Carwings-platform is uitgezet. Dat sloopte elke Leaf van vóór mei 2019 en vrijwel alle bestaande hobbyprojecten. |
| eind augustus 2026 | Nissan Europa verving de inloglaag door MyNISSAN "OneID": OAuth2 met PKCE tegen een WSO2-server op `login.mynissan-account.com`. |

De datalaag erachter (Kamereon, `*.apps.eu2.kamereon.io`) bleef ongewijzigd.

**Val niet in deze valkuil:** Gigya is het inlogsysteem van **Renault**, niet van
Nissan. Meerdere bronnen suggereren anders. De opdracht aan de bouwende agent
bevatte die fout; die agent zocht het na, concludeerde dat het niet klopte, en
schreef er een notitie bij in plaats van het uit te voeren.

De beste basis om op voort te bouwen was het `kamereon/`-package uit
`dan-r/HomeAssistant-NissanConnect` (MIT). Dat was op 1 september bijgewerkt voor
de nieuwe inlogroute.

---

## Drie echte fouten, en hoe ze zichtbaar werden

### 1. HTTP 406 bij het uitlezen van de accu

Inloggen lukte, de voertuiglijst kwam binnen, maar de accu gaf steevast
`406 Not Acceptable`.

406 betekent geen "verkeerd adres" (dat is 404) en geen "geen toegang" (401/403),
maar: *ik kan niet antwoorden in het formaat dat je vraagt.*

Oorzaak: naar beide Nissan-servers ging hetzelfde mediatype. De `car-adapter`
spreekt JSON:API, maar `bff-web` is een gewone web-API en weigert een verzoek dat
om JSON:API vraagt. Het mediatype wordt nu per server gekozen.

### 2. Opnieuw inloggen liep vast op de eigen sessie

Zichtbaar als `onverwachte host com://wso2.service.nci`.

Bij her-authenticatie had de client de sessiecookies van de eerste aanmelding
nog. Nissan sloeg het inlogformulier dan over en stuurde meteen door naar de
callback mét code — en de code die de inlogpagina ophaalt ging ervan uit dat er
altijd een formulier zou komen.

Dit was de vervelendste: het trof **elk** verzoek dat een 401 opleverde, en zou de
hele app hebben gesloopt zodra het token na ongeveer een uur verliep. Het maskeerde
bovendien de echte antwoorden, waardoor meerdere diensten ten onrechte als
onbeschikbaar leken.

### 3. Een oude service worker in de browser

Na een update toonde de pagina een foutmelding zonder naam (`Code: undefined`),
terwijl de backend perfect werkte — rechtstreeks bevragen met `Invoke-WebRequest`
gaf gewoon een correct antwoord.

De browser serveerde nog de oude JavaScript uit zijn eigen opslag. Het
privévenster werkte wél; dat is meteen de snelste manier om dit te herkennen.
Oplossing: F12 → Application → Clear site data.

---

## Wat deze auto wél en niet teruggeeft

Gemeten, niet aangenomen.

### Werkt

| Gegeven | Endpoint |
|---|---|
| Accu (percentage, bereik, laadstatus, resterende tijd, beschikbare energie) | `bff-web/v3/cars/{vin}/battery-status?canGen=...` |
| Klimaat + binnentemperatuur | `car-adapter/v1/cars/{vin}/hvac-status` |
| Voorverwarmen starten/stoppen | `car-adapter/v1/cars/{vin}/actions/hvac-start` |
| Locatie + rijrichting | `car-adapter/v1/cars/{vin}/location` |
| Kilometerstand | `car-adapter/v1/cars/{vin}/cockpit` |
| Bandenspanning per wiel | `car-adapter/v1/cars/{vin}/pressure` |

### Werkt niet, en waarom

| Gegeven | Antwoord | Conclusie |
|---|---|---|
| Deuren op slot | `car-adapter/v1` → **403**; drie andere routes → 404 | Eén echt adres, en dat weigert. Definitief niet beschikbaar. |
| Claxon | niet getest | Hoort bij hetzelfde pakket afstandsbediening als het slot; vrijwel zeker ook geweigerd. |
| Laadschema | 403 op drie routes | Geweigerd. |
| Ritgeschiedenis | 400 | Vermoedelijk ontbrekende parameters; niet verder uitgezocht. |
| Onderhoud, meldingen | 404 / 500 | Adres onbekend of kapot. |
| Accugezondheid | — | Nissan geeft alleen de fabriekscapaciteit, niet de slijtage. Echte accugezondheid vraagt een OBD-II-dongle. |

**Let op het verschil tussen 403 en 404.** 403 betekent dat het adres bestaat maar
geweigerd wordt; 404 dat het niet bestaat. Dat onderscheid was doorslaggevend bij
de conclusie over de deuren.

---

## Twee aannames die nooit bevestigd zijn

1. **Bandenspanning gedeeld door 1000 geeft bar** (2070 → 2,07 bar). Plausibel voor
   een personenauto, maar niet geverifieerd. Klopt de weergave niet met een
   bandenpompmeter, dan is dit getal de verdachte. Staat als opmerking bij
   `RAW_PRESSURE_PER_BAR`.
2. **`batteryTemperature: 0` betekent "niet gemeten"**, niet "nul graden". Een
   ladende accu is nooit precies 0. Wordt vertaald naar `null`.

En: de lijst met dienstnummers die Nissan meestuurt is **onbetrouwbaar**. Nummer
308 staat als actief gemeld terwijl het bijbehorende adres 403 geeft, en de
locatie werkt terwijl het nummer dat daarbij zou horen niet eens in de lijst
voorkomt. Vertrouw `ontdek.py` en niet die tabel.

---

## Ontwerpkeuzes die met opzet zo zijn

- **De interface vraagt eerst wat de auto kan** (`/api/capabilities`) en toont
  alleen dat. Een knop die altijd faalt is erger dan geen knop. De backend stelt
  dat vast door het één keer echt te proberen en te onthouden, zodat het ook klopt
  voor een andere auto of een ander abonnement.
- **Een rem van 15 minuten op geforceerde metingen.** Die maken de auto echt
  wakker; te vaak pollen trekt de 12V-accu leeg, en met een lege 12V doet de auto
  helemaal niets meer. Gewoon uitlezen valt hier niet onder: dat leest alleen wat
  Nissan al weet.
- **Een geweigerd wachtwoord wordt niet herhaald.** Nissan vergrendelt accounts.
- **Gemeten binnentemperatuur en streeftemperatuur staan nadrukkelijk uit elkaar.**
  Die verwarren is een fout die je zelf niet opmerkt.
- **De ouderdom van elke meting is onmisbaar zichtbaar.** Een twee uur oude
  accustand tonen alsof hij actueel is, is het ergste wat deze app kan doen.
- **Geen enkel extern verzoek vanuit de pagina.** Geen CDN, geen lettertypen, geen
  kaartdienst. De locatielink opent pas iets als je er zelf op tikt.

---

## Draaien

```powershell
# Dubbelklik "Ariya" op het bureaublad, of:
cd nissan-connect\server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

Instellingen staan in `server/.env` (buiten git gehouden). Zie `README.md` voor de
eerste installatie en `nissan-research/API-RESEARCH.md` voor het volledige
API-onderzoek.

Werkt het niet meer: de foutmeldingen zijn met opzet specifiek. Ze zeggen of het
aan het abonnement ligt, aan de inloggegevens, aan een slapende auto, of aan iets
anders. Alle Nissan-adressen en -sleutels staan bij elkaar bovenin
`server/app/vehicle/kamereon.py`, juist om een reparatie kort te houden.

Reken erop dat het platform weer verandert.
