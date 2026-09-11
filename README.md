# Tactus Angelis — Website

Website voor **Mirjam van Steenbrugge**, Shamballa master en Caropoint behandelaar in Berkel-Enschot.

Een statische site: geen build-stap, geen framework. Openen, aanpassen, klaar.

## Projectstructuur

```
.
├── index.html              # De hele pagina
├── 404.html                # Foutpagina
├── css/
│   └── style.css           # Alle styling
├── js/
│   └── main.js             # Menu, scroll-animaties, reviews
├── assets/
│   └── images/
│       ├── logo.jpeg           # Tactus Angelis logo
│       ├── mirjam_profiel.jpeg # Profielfoto Mirjam
│       ├── shamballa.jpeg      # Shamballa sfeerbeeld
│       └── qr_code.png         # QR-code naar e-mail
├── robots.txt
├── sitemap.xml
└── netlify.toml            # Deploy-instellingen voor Netlify
```

## Lokaal draaien

```bash
# Optie 1 — simpelste: dubbelklik op index.html
# Optie 2 — via Node.js:
npm start                    # draait: npx serve .

# Optie 3 — via Python:
python3 -m http.server 8000
# Open daarna http://localhost:8000
```

## Online zetten

1. Ga naar **netlify.com/drop**
2. Sleep de hele projectmap erop
3. Klaar — je krijgt een link!

Of via Netlify CLI:

```bash
npm install -g netlify-cli
npm run deploy
```

Werkt ook op GitHub Pages: zet Pages in de repo-instellingen op de branch die je wilt publiceren,
map `/ (root)`.

## Aanpassingen

| Wat aanpassen | Waar |
|---|---|
| Teksten | `index.html` |
| Kleuren / fonts | `css/style.css` (variabelen bovenaan) |
| Menu, scroll-animatie, reviews | `js/main.js` |
| Foto's | bestanden in `assets/images/` vervangen |
| Tarieven | sectie `#tarieven` in `index.html` |

### Kleuren (CSS-variabelen in `style.css`)

```css
--goud:        #C9A84C;  /* hoofdkleur */
--goud-licht:  #E2C97E;  /* licht accent */
--teal:        #0D3B47;  /* achtergrond */
--teal-donker: #0A2F3A;  /* afwisselende secties */
--teal-licht:  #0F4A59;  /* kaarten */
--tekst:       #F5EDD6;  /* tekstkleur */
```

## Over de reviews

Reviews worden opgeslagen in `localStorage` van de **bezoeker zelf**. Ze zijn dus alleen zichtbaar
op het apparaat waar ze zijn ingevuld en komen niet bij Mirjam terecht. Wil je echte, gedeelde
reviews? Dan is een formulierdienst nodig (bijvoorbeeld Netlify Forms of Formspree).

## Wat is er nieuw in deze versie

- Werkend mobiel menu (het oude menu verdween op telefoons zonder alternatief)
- Alle styling uit de HTML gehaald en in `style.css` gezet
- Toegankelijkheid: skip-link, echte formulierlabels, toetsenbordbediening, zichtbare focus
- SEO: meta-omschrijving, Open Graph, JSON-LD, `sitemap.xml` en `robots.txt`
- Reviews worden veilig weergegeven (geen HTML-injectie meer) en overleven een geblokkeerde opslag
- Leesbare footer, `prefers-reduced-motion`, lazy loading van foto's

## Contact

Website gemaakt door **Marco van Steenbrugge** — met een beetje hulp van AI ✦
