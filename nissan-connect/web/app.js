/* Ariya Connect — API-client en UI-logica.
   Geen framework, geen build-stap: dit bestand draait zoals het is. */
(() => {
  'use strict';

  /* ── Instellingen ────────────────────────────────────────── */
  const TOKEN_SLEUTEL = 'ariya_app_token';
  const POLL_MS = 3000;          // contract: elke 3 seconden pollen
  const POLL_MAX_MS = 120000;    // de Nissan-API doet er soms twee minuten over
  const TEMP_MIN = 16;
  const TEMP_MAX = 26;
  const TEMP_STAP = 1;           // de auto kent alleen hele graden
  const VERS_MIN = 10;           // < 10 min = vers
  const OUD_MIN = 60;            // >= 60 min = ronduit verouderd

  /* Bereiken van de meters. De binnentemperatuur en de bandenspanning
     hebben geen natuurlijk nulpunt; deze vensters zijn gekozen zodat de
     waarden die een personenauto werkelijk geeft in het leesbare deel
     van de boog vallen. */
  const BINNEN_MIN = -10, BINNEN_MAX = 40;   // °C in de cabine
  const BAND_MIN = 1.0, BAND_MAX = 3.0;      // bar

  /* ── Kleine hulpjes ──────────────────────────────────────── */
  const el = (id) => document.getElementById(id);
  const wacht = (ms) => new Promise((r) => setTimeout(r, ms));
  const getal = (n, cijfers = 0) =>
    n.toLocaleString('nl-NL', { minimumFractionDigits: cijfers, maximumFractionDigits: cijfers });
  const isNum = (n) => typeof n === 'number' && isFinite(n);
  const klem = (n, laag, hoog) => Math.max(laag, Math.min(hoog, n));

  /* Wie om rust vraagt, krijgt rust: geen tellende cijfers, geen
     bewegende ringen — meteen de eindwaarde. */
  const rustig = () => {
    try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; }
    catch { return false; }
  };

  /* ── Opslag (privémodus kan localStorage blokkeren) ──────── */
  const opslag = (() => {
    let geheugen = null;
    let bruikbaar = true;
    try {
      localStorage.setItem('__ariya_test', '1');
      localStorage.removeItem('__ariya_test');
    } catch {
      bruikbaar = false;
    }
    return {
      lees() {
        if (!bruikbaar) return geheugen;
        try { return localStorage.getItem(TOKEN_SLEUTEL); } catch { return geheugen; }
      },
      schrijf(waarde) {
        geheugen = waarde;
        if (!bruikbaar) return false;
        try { localStorage.setItem(TOKEN_SLEUTEL, waarde); return true; } catch { return false; }
      },
      wis() {
        geheugen = null;
        try { localStorage.removeItem(TOKEN_SLEUTEL); } catch { /* niets */ }
      },
      duurzaam: bruikbaar
    };
  })();

  /* ── Transport: echte server, of de mock bij ?mock=1 ─────── */
  const mockActief = typeof window.ARIYA_MOCK_FETCH === 'function';
  const verstuur = mockActief
    ? window.ARIYA_MOCK_FETCH
    : (pad, opties) => fetch(pad, opties);

  /* ── Fouten ──────────────────────────────────────────────── */
  class ApiFout extends Error {
    constructor(code, serverBericht, herhaalbaar, httpStatus) {
      super(code);
      this.code = code || 'onbekend';
      this.serverBericht = serverBericht || null;
      this.herhaalbaar = herhaalbaar !== false;
      this.httpStatus = httpStatus || 0;
    }
  }

  const FOUT_TEKST = {
    unauthorized:
      'Je app-token wordt niet (meer) geaccepteerd. Voer het opnieuw in.',
    nissan_auth_failed:
      'De server kon niet inloggen bij Nissan. Controleer de Nissan-gegevens op de server.',
    vehicle_asleep:
      'De auto reageert niet — waarschijnlijk staat hij in slaapstand. Probeer het over een paar minuten opnieuw.',
    rate_limited:
      'Nissan laat even geen nieuwe opdrachten toe. Wacht een paar minuten en probeer het dan nog eens.',
    not_plugged_in:
      'De laadkabel zit er niet in. Deze opdracht kan alleen met de stekker in de auto.',
    upstream_error:
      'Nissan geeft een storing terug. Dat ligt niet aan jou — probeer het straks opnieuw.',
    invalid_request:
      'De opdracht werd geweigerd omdat er iets niet klopt. Controleer de temperatuur: hele graden van 16 tot 26 °C.',
    netwerk:
      'Geen verbinding met de server. Staat de server aan en heb je internet?',
    ongeldig_antwoord:
      'De server gaf een antwoord dat de app niet begrijpt.',
    job_timeout:
      'De auto gaf niet op tijd antwoord. Meestal betekent dat: hij slaapt. Probeer het zo nog eens.',
    client_timeout:
      'Na twee minuten wachten nog geen antwoord. De opdracht kan alsnog aankomen — wacht even en ververs daarna.'
  };

  function foutRegel(fout) {
    if (FOUT_TEKST[fout.code]) return FOUT_TEKST[fout.code];
    // Kent de app deze code niet (bijv. een nieuwe code van de server), dan is het
    // Nederlandse bericht van de server zelf beter dan een vage standaardzin.
    if (fout.serverBericht) return fout.serverBericht;
    if (fout.httpStatus >= 500) return 'De server heeft een storing (code ' + fout.httpStatus + ').';
    if (fout.httpStatus >= 400) return 'De server wees de opdracht af (code ' + fout.httpStatus + ').';
    return 'Er ging iets mis waar de app geen naam voor heeft.';
  }

  /* ── API-client ──────────────────────────────────────────── */
  async function api(pad, { methode = 'GET', body = null } = {}) {
    const kop = { Accept: 'application/json' };
    if (body !== null) kop['Content-Type'] = 'application/json';
    const token = opslag.lees();
    if (token) kop.Authorization = 'Bearer ' + token;

    let antwoord;
    try {
      antwoord = await verstuur(pad, {
        method: methode,
        headers: kop,
        body: body === null ? undefined : JSON.stringify(body),
        cache: 'no-store'
      });
    } catch {
      throw new ApiFout('netwerk', null, true, 0);
    }

    let data = null;
    try { data = await antwoord.json(); } catch { data = null; }

    if (!antwoord.ok) {
      const f = (data && data.error) || {};
      const code = f.code || (antwoord.status === 401 ? 'unauthorized' : 'http_' + antwoord.status);
      throw new ApiFout(code, f.message, f.retryable, antwoord.status);
    }
    if (data === null) throw new ApiFout('ongeldig_antwoord', null, false, antwoord.status);
    return data;
  }

  const haalVoertuig = () => api('api/vehicle');
  const haalMogelijkheden = () => api('api/capabilities');
  const haalAccu = () => api('api/battery');
  const haalKlimaat = () => api('api/climate');
  const haalBanden = () => api('api/tyres');
  const haalKilometerstand = () => api('api/odometer');
  const haalLocatie = () => api('api/location');
  const startVerversen = () => api('api/battery/refresh', { methode: 'POST', body: {} });
  const startKlimaat = (temp) => api('api/climate/start', { methode: 'POST', body: { target_temp_c: temp } });
  const stopKlimaat = () => api('api/climate/stop', { methode: 'POST', body: {} });
  const haalJob = (id) => api('api/jobs/' + encodeURIComponent(String(id)));

  function jobNaarFout(job) {
    const e = job && job.error;
    if (typeof e === 'string') {
      return new ApiFout(job && job.status === 'timeout' ? 'job_timeout' : 'upstream_error', e, true, 0);
    }
    // Bij een timeout is "de auto antwoordde niet op tijd" het eerlijke verhaal,
    // ook als de server er een code bij levert; die komt als detail mee.
    const code = job && job.status === 'timeout'
      ? 'job_timeout'
      : (e && e.code) || 'upstream_error';
    return new ApiFout(code, e && e.message, e && e.retryable, 0);
  }

  /* ══════════════════════════════════════════════════════════
     De radiale meter — één component voor alle zes de meters

     Geparametriseerd op bereik, eenheid, aantal streepjes en ernst.
     De SVG is decoratief (aria-hidden); de waarde staat als échte
     tekst in het midden, zodat een schermlezer hem gewoon voorleest.
     ══════════════════════════════════════════════════════════ */

  /* Statuskleuren zijn gereserveerd en vast (zie style.css). De
     onopgevulde baan is telkens dezelfde kleur, één stap richting het
     kaartvlak — nooit grijs, zodat de toestand over de hele ring leest.
     "meting" is geen toestand maar een aflezing: koel blauw, en zonder
     statuswoord, want er valt niets te beoordelen. */
  const ERNST = {
    goed:     { vul: 'var(--goed)',    baan: 'var(--goed-baan)',    teken: '✓' },
    'let-op': { vul: 'var(--let-op)',  baan: 'var(--let-op-baan)',  teken: '!' },
    ernstig:  { vul: 'var(--ernstig)', baan: 'var(--ernstig-baan)', teken: '!' },
    kritiek:  { vul: 'var(--kritiek)', baan: 'var(--kritiek-baan)', teken: '⚠' },
    meting:   { vul: 'var(--koel)',    baan: 'var(--koel-baan)',    teken: '○' },
    onbekend: { vul: 'var(--tekst-gedempt)', baan: 'var(--rand)',   teken: '?' }
  };

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const BOOG_START = 225;   // graden, met de klok mee vanaf 12 uur: linksonder
  const BOOG_SWEEP = 270;   // opening van 90° recht onderaan
  const BOOG_R = 40;
  const BOOG_LENGTE = (BOOG_SWEEP / 360) * 2 * Math.PI * BOOG_R;

  function svgEl(naam, kenmerken) {
    const e = document.createElementNS(SVG_NS, naam);
    Object.keys(kenmerken).forEach((k) => e.setAttribute(k, kenmerken[k]));
    return e;
  }

  /* Punt op de cirkel; hoek in graden, met de klok mee vanaf 12 uur. */
  function boogPunt(hoek, straal) {
    const r = (hoek * Math.PI) / 180;
    return [50 + straal * Math.sin(r), 50 - straal * Math.cos(r)];
  }

  /* Cijfers die bij het laden één keer naar hun waarde tellen.
     Daarna — bij een verversing — springt de waarde er meteen heen:
     tellen is een begroeting, geen tic. */
  const alGeteld = new Set();
  function zetGetal(node, waarde, opmaak, sleutel) {
    if (waarde === null) { node.textContent = '–'; return; }
    if (!sleutel || alGeteld.has(sleutel) || rustig()) {
      node.textContent = opmaak(waarde);
      if (sleutel) alGeteld.add(sleutel);
      return;
    }
    alGeteld.add(sleutel);
    const duur = 900;
    const begin = performance.now();
    const stap = (nu) => {
      const t = Math.min(1, (nu - begin) / duur);
      const e = 1 - Math.pow(1 - t, 3);           // rustig uitlopend
      node.textContent = opmaak(waarde * e);
      if (t < 1) requestAnimationFrame(stap);
      else node.textContent = opmaak(waarde);
    };
    requestAnimationFrame(stap);
  }

  /**
   * Bouwt één radiale meter in `opt.houder`.
   *
   * opt.min, opt.max   bereik van de boog
   * opt.eenheid        tekst achter het getal ('%', '°C', 'bar', …)
   * opt.cijfers        aantal decimalen
   * opt.tikken         aantal segmenten tussen de schaalstreepjes
   * opt.grofElke       elk hoeveelste streepje een grove is
   * opt.telSleutel     sleutel voor het eenmalige optellen (weglaten = niet tellen)
   * opt.label          korte zin die een schermlezer vóór de waarde hoort
   *
   * Geeft terug: { zet({ waarde, ernst, woord }) }
   */
  function maakMeter(opt) {
    const houder = opt.houder;
    const min = opt.min, max = opt.max;
    const cijfers = opt.cijfers || 0;
    const tikken = opt.tikken || 40;
    const grofElke = opt.grofElke || 10;

    const svg = svgEl('svg', {
      viewBox: '0 0 100 100', class: 'meter-svg',
      'aria-hidden': 'true', focusable: 'false'
    });

    /* Dunne buitenring. */
    svg.append(svgEl('circle', { class: 'meter-ring', cx: 50, cy: 50, r: 47 }));

    /* Fijne schaalstreepjes — terughoudend; de waarde is de hoofdpersoon. */
    const tikGroep = svgEl('g', { class: 'meter-tikken' });
    for (let i = 0; i <= tikken; i++) {
      const grof = i % grofElke === 0;
      const hoek = BOOG_START + (i / tikken) * BOOG_SWEEP;
      const [x1, y1] = boogPunt(hoek, grof ? 43.0 : 44.5);
      const [x2, y2] = boogPunt(hoek, 46.4);
      tikGroep.append(svgEl('line', {
        class: 'meter-tik' + (grof ? ' meter-tik--grof' : ''),
        x1: x1.toFixed(2), y1: y1.toFixed(2), x2: x2.toFixed(2), y2: y2.toFixed(2)
      }));
    }
    svg.append(tikGroep);

    const [ax, ay] = boogPunt(BOOG_START, BOOG_R);
    const [bx, by] = boogPunt(BOOG_START + BOOG_SWEEP, BOOG_R);
    const d = 'M ' + ax.toFixed(3) + ' ' + ay.toFixed(3) +
              ' A ' + BOOG_R + ' ' + BOOG_R + ' 0 1 1 ' + bx.toFixed(3) + ' ' + by.toFixed(3);

    svg.append(svgEl('path', { class: 'meter-baan', d, 'stroke-dasharray': 'none' }));

    const L = BOOG_LENGTE.toFixed(3);
    const bogen = [
      svgEl('path', { class: 'meter-gloed meter-gloed--buiten', d }),
      svgEl('path', { class: 'meter-gloed meter-gloed--binnen', d }),
      svgEl('path', { class: 'meter-vul', d })
    ];
    bogen.forEach((p) => {
      p.setAttribute('stroke-dasharray', L + ' ' + L);
      p.setAttribute('stroke-dashoffset', L);
      svg.append(p);
    });

    /* Het kopje op het einde van de boog draait mee met de waarde. */
    const wijzer = svgEl('g', { class: 'meter-wijzer', transform: 'rotate(0 50 50)' });
    wijzer.append(svgEl('circle', {
      class: 'meter-punt', cx: ax.toFixed(3), cy: ay.toFixed(3), r: opt.klein ? 2.8 : 3.2
    }));
    svg.append(wijzer);

    /* Het label komt vóór de SVG te staan, zodat een schermlezer eerst
       hoort wát hij leest en daarna de waarde. */
    const zin = document.createElement('p');
    zin.className = 'visueel-verborgen';
    zin.textContent = opt.label || '';

    const midden = document.createElement('div');
    midden.className = 'meter-midden';

    const waardeRegel = document.createElement('p');
    waardeRegel.className = 'meter-waarde';
    const getalSpan = document.createElement('span');
    getalSpan.className = 'meter-getal';
    getalSpan.textContent = '–';
    waardeRegel.append(getalSpan);
    if (opt.eenheid) {
      const eenheidSpan = document.createElement('span');
      eenheidSpan.className = 'meter-eenheid';
      eenheidSpan.textContent = opt.eenheid;
      waardeRegel.append(eenheidSpan);
    }
    midden.append(waardeRegel);

    const staat = document.createElement('p');
    staat.className = 'meter-staat';
    staat.hidden = true;
    const staatTeken = document.createElement('span');
    staatTeken.className = 'meter-staat-teken';
    staatTeken.setAttribute('aria-hidden', 'true');
    const staatWoord = document.createElement('span');
    staat.append(staatTeken, staatWoord);
    midden.append(staat);

    houder.replaceChildren(zin, svg, midden);
    houder.classList.add('meter--leeg');

    return {
      zet(stand) {
        const waarde = isNum(stand.waarde) ? stand.waarde : null;
        const ernst = ERNST[stand.ernst] ? stand.ernst : 'onbekend';
        const kleur = ERNST[ernst];

        houder.style.setProperty('--vul', kleur.vul);
        houder.style.setProperty('--baan', kleur.baan);
        houder.classList.toggle('meter--leeg', waarde === null);

        const deel = waarde === null ? 0 : klem((waarde - min) / (max - min), 0, 1);
        bogen.forEach((p) => p.setAttribute('stroke-dashoffset', (BOOG_LENGTE * (1 - deel)).toFixed(3)));
        wijzer.setAttribute('transform', 'rotate(' + (deel * BOOG_SWEEP).toFixed(2) + ' 50 50)');

        zetGetal(getalSpan, waarde, (n) => getal(n, cijfers), opt.telSleutel);

        if (stand.woord) {
          staat.hidden = false;
          staatTeken.textContent = kleur.teken;
          staatWoord.textContent = stand.woord;
        } else {
          staat.hidden = true;
        }
      }
    };
  }

  /* ── De zes meters ───────────────────────────────────────── */
  const meterAccu = maakMeter({
    houder: el('meter-accu'),
    min: 0, max: 100, eenheid: '%', cijfers: 0,
    tikken: 40, grofElke: 10,
    telSleutel: 'accu',
    label: 'Laadstand van de accu:'
  });

  const meterBinnen = maakMeter({
    houder: el('meter-binnen'),
    min: BINNEN_MIN, max: BINNEN_MAX, eenheid: '°C', cijfers: 1,
    tikken: 30, grofElke: 6,
    telSleutel: 'binnen',
    label: 'Gemeten temperatuur in de auto:'
  });

  const WIELEN = [
    ['front_left', 'Linksvoor'],
    ['front_right', 'Rechtsvoor'],
    ['rear_left', 'Linksachter'],
    ['rear_right', 'Rechtsachter']
  ];

  const bandMeters = {};
  WIELEN.forEach(([sleutel]) => {
    bandMeters[sleutel] = maakMeter({
      houder: el('meter-' + sleutel),
      min: BAND_MIN, max: BAND_MAX, eenheid: 'bar', cijfers: 2,
      tikken: 20, grofElke: 5, klein: true,
      telSleutel: 'band-' + sleutel
      // Geen eigen label: het bandkaartje eromheen noemt de plek al,
      // zichtbaar én in zijn aria-label.
    });
  });

  /* ── Meldingen ───────────────────────────────────────────── */
  function meld(tekst, soort, detail) {
    const vak = el('melding');
    vak.hidden = false;
    vak.className = 'melding' + (soort ? ' melding--' + soort : '');
    vak.setAttribute('aria-live', soort === 'fout' ? 'assertive' : 'polite');
    el('melding-tekst').textContent = tekst;
    const d = el('melding-detail');
    d.textContent = detail || '';
    d.hidden = !detail;
  }
  function meldingWeg() {
    el('melding').hidden = true;
    el('melding-tekst').textContent = '';
    el('melding-detail').textContent = '';
  }

  function toonFout(fout, context) {
    if (fout.code === 'unauthorized' || fout.httpStatus === 401) {
      opslag.wis();
      toonTokenScherm('Je token werd geweigerd door de server. Voer het opnieuw in.');
      return;
    }
    const delen = [];
    if (context) delen.push(context);
    if (fout.serverBericht && fout.serverBericht !== foutRegel(fout)) delen.push('Server: ' + fout.serverBericht);
    if (!FOUT_TEKST[fout.code] && !String(fout.code).startsWith('http_')) delen.push('Code: ' + fout.code);
    meld(foutRegel(fout), 'fout', delen.join(' · '));
  }

  /* ── Leeftijd van de accumeting ──────────────────────────── */
  let leeftijdBasisMs = null;   // hoe oud de meting was toen we 'm ophaalden
  let leeftijdGemetenOp = 0;    // wanneer wij die waarde kregen

  function zetLeeftijdBron(accu) {
    leeftijdGemetenOp = Date.now();
    if (accu && isNum(accu.stale_minutes)) {
      leeftijdBasisMs = Math.max(0, accu.stale_minutes) * 60000;
      return;
    }
    const t = accu && accu.updated_at ? Date.parse(accu.updated_at) : NaN;
    leeftijdBasisMs = isNaN(t) ? null : Math.max(0, Date.now() - t);
  }

  function leeftijdTekst(ms) {
    const minuten = Math.floor(ms / 60000);
    if (minuten < 1) return 'zojuist';
    if (minuten === 1) return '1 minuut geleden';
    if (minuten < 60) return minuten + ' minuten geleden';
    const uren = Math.floor(minuten / 60);
    const rest = minuten % 60;
    if (uren < 24) {
      return uren + (uren === 1 ? ' uur' : ' uur') + (rest ? ' en ' + rest + ' min' : '') + ' geleden';
    }
    const dagen = Math.floor(uren / 24);
    return dagen === 1 ? 'meer dan een dag geleden' : dagen + ' dagen geleden';
  }

  function werkLeeftijdBij() {
    const vak = el('leeftijd');
    const tekst = el('leeftijd-tekst');

    if (leeftijdBasisMs === null) {
      vak.className = 'leeftijd leeftijd--onbekend';
      tekst.textContent = leeftijdGemetenOp
        ? 'Onbekend hoe oud deze meting is — ververs voor zekerheid'
        : 'Nog niet opgehaald';
      return;
    }
    const ms = leeftijdBasisMs + (Date.now() - leeftijdGemetenOp);
    const minuten = ms / 60000;
    if (minuten < VERS_MIN) {
      vak.className = 'leeftijd leeftijd--vers';
      tekst.textContent = 'Actueel · gemeten ' + leeftijdTekst(ms);
    } else if (minuten < OUD_MIN) {
      vak.className = 'leeftijd leeftijd--oud';
      tekst.textContent = 'Let op: gemeten ' + leeftijdTekst(ms);
    } else {
      vak.className = 'leeftijd leeftijd--zeer-oud';
      tekst.textContent = 'VEROUDERD · gemeten ' + leeftijdTekst(ms) + ' — ververs eerst';
    }
  }
  setInterval(werkLeeftijdBij, 15000);

  /* ── Wat kan déze auto? ──────────────────────────────────────
     De server bepaalt het, de pagina schikt zich ernaar. Elk vak met
     data-vereist="x" verschijnt alleen als /api/capabilities zegt dat x
     kan. Zo hoeft er nergens anders in deze app een lijstje bijgehouden
     te worden: een nieuw onderdeel toevoegen is één attribuut in de HTML. */
  const ONDERDEEL_NAAM = {
    battery: 'accu',
    climate: 'voorverwarmen',
    location: 'locatie',
    odometer: 'kilometerstand',
    tyres: 'bandenspanning',
    doors: 'deuren',
    charge_schedule: 'laadschema'
  };

  let mogelijk = Object.create(null);
  const kan = (naam) => mogelijk[naam] === true;

  /* Blijft een hele kolom leeg, dan verdwijnt ook de kolom zelf en
     krimpt het raster mee — geen lege baan naast de rest. */
  function schikKolommen() {
    const raster = el('raster');
    [['accu', 'kolom-accu'], ['temp', 'kolom-temp'], ['overig', 'kolom-overig']]
      .forEach(([naam, id]) => {
        const kolom = el(id);
        kolom.hidden = !kolom.querySelector('.kaart:not([hidden])');
        raster.classList.toggle('zonder-' + naam, kolom.hidden);
      });
  }

  function pasMogelijkhedenToe(caps) {
    mogelijk = Object.create(null);
    if (caps && typeof caps === 'object') {
      Object.keys(caps).forEach((sleutel) => { mogelijk[sleutel] = caps[sleutel] === true; });
    }

    let zichtbaar = 0;
    document.querySelectorAll('[data-vereist]').forEach((vak) => {
      const aan = kan(vak.dataset.vereist);
      vak.hidden = !aan;
      if (aan) zichtbaar += 1;
    });
    el('niets-melding').hidden = zichtbaar > 0;
    schikKolommen();

    const wel = [];
    const niet = [];
    Object.keys(mogelijk).forEach((sleutel) => {
      const naam = ONDERDEEL_NAAM[sleutel] || sleutel;
      (mogelijk[sleutel] ? wel : niet).push(naam);
    });
    const regels = [];
    if (wel.length) regels.push('Beschikbaar: ' + wel.join(', ') + '.');
    if (niet.length) regels.push('Niet op deze auto: ' + niet.join(', ') + '.');
    el('menu-mogelijkheden').textContent = regels.join(' ') || 'De server meldde geen onderdelen.';
  }

  /* Geeft de server geen (bruikbare) lijst, dan tonen we alleen wat er vóór
     deze uitbreiding al werkte. Liever een onderdeel te weinig dan een knop
     die het bij deze auto altijd begeeft. */
  function valMogelijkhedenTerug(reden) {
    pasMogelijkhedenToe({ battery: true, climate: true });
    el('menu-mogelijkheden').textContent =
      'De server gaf geen lijst met onderdelen (' + reden + '). Alleen accu en voorverwarmen worden getoond.';
  }

  /* ── Omrekeningen die de gebruiker moet kunnen lezen ─────── */

  /* 254 minuten → "nog 4 uur 14" */
  function laadtijdKort(minuten) {
    const m = Math.max(0, Math.round(minuten));
    if (m < 1) return 'bijna klaar';
    if (m < 60) return 'nog ' + m + ' min';
    const uren = Math.floor(m / 60);
    const rest = m % 60;
    return 'nog ' + uren + ' uur' + (rest ? ' ' + String(rest).padStart(2, '0') : '');
  }
  function laadtijdLang(minuten) {
    const m = Math.max(0, Math.round(minuten));
    if (m < 1) return 'Nog minder dan een minuut laden.';
    if (m < 60) return 'Nog ' + m + (m === 1 ? ' minuut' : ' minuten') + ' laden.';
    const uren = Math.floor(m / 60);
    const rest = m % 60;
    return 'Nog ' + uren + (uren === 1 ? ' uur' : ' uur') +
      (rest ? ' en ' + rest + (rest === 1 ? ' minuut' : ' minuten') : '') + ' laden.';
  }

  /* 298° → west-noordwest (WNW). 16 streken, want dat is wat je nog kunt lezen. */
  const STREKEN = [
    ['noord', 'N'], ['noord-noordoost', 'NNO'], ['noordoost', 'NO'], ['oost-noordoost', 'ONO'],
    ['oost', 'O'], ['oost-zuidoost', 'OZO'], ['zuidoost', 'ZO'], ['zuid-zuidoost', 'ZZO'],
    ['zuid', 'Z'], ['zuid-zuidwest', 'ZZW'], ['zuidwest', 'ZW'], ['west-zuidwest', 'WZW'],
    ['west', 'W'], ['west-noordwest', 'WNW'], ['noordwest', 'NW'], ['noord-noordwest', 'NNW']
  ];
  function streek(graden) {
    const g = ((graden % 360) + 360) % 360;
    return STREKEN[Math.round(g / 22.5) % 16];
  }

  /* ── Bandenspanning tonen ────────────────────────────────── */
  function toonBanden(banden) {
    const slecht = [];
    let onbekend = 0;

    WIELEN.forEach(([sleutel, plek]) => {
      const vak = el('band-' + sleutel);
      const wiel = banden && banden[sleutel];
      const bar = wiel && isNum(wiel.bar) ? wiel.bar : null;
      const inOrde = wiel ? wiel.ok : null;

      const teken = vak.querySelector('.band-teken');
      const woord = vak.querySelector('.band-woord');

      // Ook het wiel in de tekening kleurt mee, zodat de plek klopt met het getal.
      const wielVorm = el('wiel-' + sleutel);

      let ernst;
      if (inOrde === false) {
        ernst = 'kritiek';
        vak.className = 'band band--' + plekKlasse(sleutel) + ' band--let-op';
        teken.textContent = '⚠';          // pictogram, náást het woord
        woord.textContent = 'CONTROLEREN';
        if (wielVorm) wielVorm.setAttribute('class', 'auto-wiel let-op');
        slecht.push(plek.toLowerCase());
      } else if (inOrde === true) {
        ernst = 'goed';
        vak.className = 'band band--' + plekKlasse(sleutel) + ' band--in-orde';
        teken.textContent = '✓';
        woord.textContent = 'in orde';
        if (wielVorm) wielVorm.setAttribute('class', 'auto-wiel');
      } else {
        ernst = 'onbekend';
        vak.className = 'band band--' + plekKlasse(sleutel) + ' band--onbekend';
        teken.textContent = '?';
        woord.textContent = bar === null ? 'niet doorgegeven' : 'staat onbekend';
        if (wielVorm) wielVorm.setAttribute('class', 'auto-wiel onbekend');
        onbekend += 1;
      }

      bandMeters[sleutel].zet({ waarde: bar, ernst });

      // Eén zin per wiel voor de schermlezer; los van de ruimtelijke opmaak.
      vak.setAttribute('aria-label',
        plek + ': ' + (bar === null ? 'druk niet doorgegeven' : getal(bar, 2) + ' bar') +
        (inOrde === false ? ', controleren' : inOrde === true ? ', in orde' : ', staat onbekend'));
    });

    const alarm = el('banden-alarm');
    if (slecht.length) {
      alarm.hidden = false;
      el('banden-alarm-tekst').textContent = slecht.length === 1
        ? 'De band ' + slecht[0] + ' is niet in orde. Controleer hem voor je wegrijdt.'
        : 'Deze banden zijn niet in orde: ' + slecht.join(', ') + '. Controleer ze voor je wegrijdt.';
    } else {
      alarm.hidden = true;
      el('banden-alarm-tekst').textContent = '';
    }

    const noot = el('banden-leeftijd');
    const gemeten = leeftijdVan(banden);
    if (gemeten !== null) noot.textContent = 'Gemeten ' + leeftijdTekst(gemeten) + '.';
    else if (onbekend === 4) noot.textContent = 'De auto gaf geen bandgegevens door.';
    else noot.textContent = '';
  }

  function plekKlasse(sleutel) {
    return { front_left: 'lv', front_right: 'rv', rear_left: 'la', rear_right: 'ra' }[sleutel] || 'lv';
  }

  /* ── Kilometerstand tonen ────────────────────────────────── */
  function toonKilometerstand(stand) {
    const km = stand && isNum(stand.total_km) ? stand.total_km : null;
    zetGetal(el('km-getal'), km, (n) => getal(Math.round(n)), 'km');   // 21.126
    el('km-eenheid').hidden = km === null;

    const gemeten = leeftijdVan(stand);
    el('km-leeftijd').textContent = km === null
      ? 'De auto gaf geen kilometerstand door.'
      : (gemeten === null ? 'Zoals de auto hem het laatst doorgaf.' : 'Gemeten ' + leeftijdTekst(gemeten) + '.');
  }

  /* ── Locatie tonen ───────────────────────────────────────── */
  let laatsteLocatie = null;

  function toonLocatie(plek) {
    const lat = plek && isNum(plek.latitude) ? plek.latitude : null;
    const lon = plek && isNum(plek.longitude) ? plek.longitude : null;
    const kop = plek && isNum(plek.heading_degrees) ? plek.heading_degrees : null;

    laatsteLocatie = (lat !== null && lon !== null) ? { lat, lon } : null;

    const richting = el('richting-tekst');
    const graden = el('richting-graden');
    const naald = el('kompas-naald');
    const titel = el('kompas-titel');

    if (kop === null) {
      richting.textContent = 'Richting onbekend';
      graden.textContent = 'De auto gaf geen kompasrichting door';
      naald.setAttribute('transform', 'rotate(0 50 50)');
      naald.style.opacity = '0.25';
      titel.textContent = 'Kompas: richting onbekend';
    } else {
      const [naam, afkorting] = streek(kop);
      const rond = Math.round(((kop % 360) + 360) % 360);
      richting.textContent = 'Neus naar ' + naam;
      graden.textContent = rond + '° · ' + afkorting;
      naald.setAttribute('transform', 'rotate(' + rond + ' 50 50)');
      naald.style.opacity = '1';
      titel.textContent = 'Kompas: de auto wijst naar ' + naam + ', ' + rond + ' graden.';
    }

    const coord = el('coord');
    const link = el('kaart-link');
    const kopieer = el('coord-kopieer');

    if (laatsteLocatie === null) {
      coord.textContent = 'De auto gaf geen coördinaten door.';
      link.hidden = true;
      kopieer.hidden = true;
    } else {
      coord.textContent = getal(lat, 6) + ', ' + getal(lon, 6);
      // Alleen een href: er gaat pas iets naar buiten als de gebruiker zelf tikt.
      const a = lat.toFixed(6);
      const b = lon.toFixed(6);
      link.href = 'https://www.openstreetmap.org/?mlat=' + a + '&mlon=' + b + '#map=17/' + a + '/' + b;
      link.hidden = false;
      kopieer.hidden = false;
    }

    const gemeten = leeftijdVan(plek);
    el('locatie-leeftijd').textContent = gemeten === null ? '' : 'Gemeten ' + leeftijdTekst(gemeten) + '.';
  }

  /* Leeftijd (in ms) uit stale_minutes of updated_at; null als onbekend. */
  function leeftijdVan(data) {
    if (data && isNum(data.stale_minutes)) {
      return Math.max(0, data.stale_minutes) * 60000;
    }
    const t = data && data.updated_at ? Date.parse(data.updated_at) : NaN;
    return isNaN(t) ? null : Math.max(0, Date.now() - t);
  }

  /* ── Accu tonen ──────────────────────────────────────────── */
  /* Vier stappen, met bij elke stap een woord — kleur staat er nooit alleen voor. */
  function accuErnst(soc) {
    if (soc === null) return { ernst: 'onbekend', woord: 'stand onbekend' };
    if (soc <= 10) return { ernst: 'kritiek', woord: 'bijna leeg' };
    if (soc <= 20) return { ernst: 'ernstig', woord: 'laag' };
    if (soc <= 35) return { ernst: 'let-op', woord: 'raakt leeg' };
    return { ernst: 'goed', woord: 'ruim voldoende' };
  }

  function toonAccu(accu) {
    const soc = isNum(accu.soc_percent) ? klem(accu.soc_percent, 0, 100) : null;
    const staat = accuErnst(soc);
    meterAccu.zet({ waarde: soc, ernst: staat.ernst, woord: staat.woord });

    const bereikBekend = isNum(accu.range_km);
    zetGetal(el('bereik-getal'), bereikBekend ? accu.range_km : null, (n) => getal(Math.round(n)), 'bereik');
    el('bereik-eenheid').hidden = !bereikBekend;
    el('bereik-label').textContent = bereikBekend ? 'Actieradius' : 'Actieradius onbekend';

    const stekker = el('chip-stekker');
    if (accu.plugged_in === true) {
      stekker.textContent = 'Stekker aangesloten';
      stekker.className = 'chip chip--aan';
    } else if (accu.plugged_in === false) {
      stekker.textContent = 'Geen laadkabel';
      stekker.className = 'chip chip--stil';
    } else {
      stekker.textContent = 'Stekker onbekend';
      stekker.className = 'chip chip--neutraal';
    }

    const laden = el('chip-laden');
    if (accu.charging === true) {
      laden.textContent = 'Aan het laden';
      laden.className = 'chip chip--aan chip--laadt';
    } else if (accu.charging === false) {
      laden.textContent = accu.plugged_in === true ? 'Laadt niet' : 'Niet aan het laden';
      laden.className = 'chip chip--stil';
    } else {
      laden.textContent = 'Laadstatus onbekend';
      laden.className = 'chip chip--neutraal';
    }

    const soh = el('chip-soh');
    if (isNum(accu.state_of_health_percent)) {
      soh.hidden = false;
      soh.textContent = 'Accugezondheid ' + getal(accu.state_of_health_percent) + '%';
      soh.className = 'chip ' + (accu.state_of_health_percent < 80 ? 'chip--let-op' : 'chip--stil');
    } else {
      soh.hidden = true;
    }

    /* Beschikbare energie in de accu (batteryAvailableEnergy). */
    const energie = el('chip-energie');
    if (isNum(accu.available_energy_kwh)) {
      energie.hidden = false;
      const kwh = accu.available_energy_kwh;
      energie.textContent = 'Beschikbaar ' + getal(kwh, Number.isInteger(kwh) ? 0 : 1) + ' kWh';
    } else {
      energie.hidden = true;
    }

    /* Accutemperatuur levert deze auto normaal niet; tonen als hij het wél doet. */
    const accutemp = el('chip-accutemp');
    if (isNum(accu.battery_temperature_c)) {
      accutemp.hidden = false;
      accutemp.textContent = 'Accu ' + getal(accu.battery_temperature_c, 0) + ' °C';
    } else {
      accutemp.hidden = true;
    }

    /* Resterende laadtijd: alleen als de auto daadwerkelijk laadt. Een
       restduur bij een auto die niet laadt is een oud getal dat niets betekent. */
    const laadtijd = el('laadtijd');
    const minuten = accu.charging_remaining_minutes;
    if (accu.charging === true && isNum(minuten) && minuten >= 0) {
      laadtijd.hidden = false;
      el('laadtijd-waarde').textContent = laadtijdKort(minuten);   // "nog 4 uur 14"
      el('laadtijd-lang').textContent = laadtijdLang(minuten);
    } else {
      laadtijd.hidden = true;
      el('laadtijd-waarde').textContent = '–';
      el('laadtijd-lang').textContent = '';
    }

    zetLeeftijdBron(accu);
    werkLeeftijdBij();
  }

  /* ── Klimaat tonen ───────────────────────────────────────── */
  let tempAangeraakt = false;
  let gewensteTemp = 21;
  let klimaatDraait = false;
  let serverTemp = null;

  function zetTemp(waarde, vanServer) {
    const t = Math.min(TEMP_MAX, Math.max(TEMP_MIN, Math.round(waarde)));
    gewensteTemp = t;
    el('temp-schuif').value = String(gewensteTemp);
    el('temp-waarde').firstChild.nodeValue = String(gewensteTemp);
    el('temp-schuif').setAttribute('aria-valuetext', gewensteTemp + ' graden Celsius');
    el('temp-min').disabled = gewensteTemp <= TEMP_MIN;
    el('temp-plus').disabled = gewensteTemp >= TEMP_MAX;
    if (!vanServer) tempAangeraakt = true;
    werkStartKnopBij();
  }

  /* De temperatuur is geen losse opdracht: hij gaat mee met "starten".
     Dat staat op de knop zelf, zodat er geen twijfel over kan bestaan. */
  function werkStartKnopBij() {
    const knop = el('klimaat-start');
    const tekst = 'Voorverwarmen starten op ' + gewensteTemp + ' °C';
    if (knop.disabled) knop.dataset.label = tekst;
    else knop.textContent = tekst;

    const noot = el('temp-koppel-noot');
    if (klimaatDraait && tempAangeraakt && gewensteTemp !== serverTemp) {
      noot.textContent = 'De auto warmt nu voor op ' + (serverTemp === null ? 'een andere stand' : serverTemp + ' °C') +
        '. Deze ' + gewensteTemp + ' °C geldt pas als je opnieuw start.';
      noot.classList.add('instelgroep-noot--let-op');
    } else {
      noot.textContent = 'De temperatuur gaat mee op het moment dat je hieronder start. Los opslaan kan de auto niet.';
      noot.classList.remove('instelgroep-noot--let-op');
    }
  }

  function toonKlimaat(klimaat) {
    const vak = el('klimaat-status');
    const temp = isNum(klimaat.target_temp_c) ? Math.round(klimaat.target_temp_c) : null;
    klimaatDraait = klimaat.running === true;
    serverTemp = temp;

    if (klimaat.running === true) {
      vak.className = 'klimaat-status klimaat-status--aan';
      vak.textContent = 'Voorverwarmen staat AAN' + (temp !== null ? ' op ' + temp + ' °C' : '');
    } else if (klimaat.running === false) {
      vak.className = 'klimaat-status';
      vak.textContent = 'Voorverwarmen staat uit' + (temp !== null ? ' · laatst gebruikt: ' + temp + ' °C' : '');
    } else {
      vak.className = 'klimaat-status';
      vak.textContent = 'Onbekend of het voorverwarmen aan staat';
    }

    // Draait het voorverwarmen, dan is "stoppen" de knop die je in het donker
    // meteen moet kunnen vinden; anders is "starten" de hoofdknop.
    const aan = klimaat.running === true;
    el('klimaat-start').className = 'knop knop--groot ' + (aan ? 'knop--rand' : 'knop--primair');
    el('klimaat-stop').className = 'knop knop--groot knop--los ' + (aan ? 'knop--primair' : 'knop--rand');

    /* De gemeten binnentemperatuur is iets ánders dan de streeftemperatuur.
       Daarom een eigen meter — iets wat je afleest — met één decimaal
       (16,0 °C) tegenover de hele graden van de instelling, en in de koele
       "meting"-kleur in plaats van een statuskleur: er valt hier niets te
       beoordelen, alleen af te lezen. De instelling blijft knoppen en een
       schuif, en krijgt nadrukkelijk géén meter. */
    const meting = el('binnen-meting');
    const binnen = klimaat.internal_temperature_c;
    if (isNum(binnen)) {
      meting.hidden = false;
      meterBinnen.zet({ waarde: binnen, ernst: 'meting' });
    } else {
      meting.hidden = true;
      meterBinnen.zet({ waarde: null, ernst: 'onbekend' });
    }

    if (temp !== null && !tempAangeraakt) zetTemp(temp, true);
    else werkStartKnopBij();
  }

  /* ── Voortgang van een opdracht ──────────────────────────── */
  function maakVoortgang(wrapId, balkId, vulId, tekstId, fasen) {
    let timer = null;
    let start = 0;
    const wrap = el(wrapId);
    const balk = el(balkId);
    const vul = el(vulId);
    const tekst = el(tekstId);

    const tik = () => {
      const s = Math.floor((Date.now() - start) / 1000);
      const maxS = POLL_MAX_MS / 1000;
      vul.style.width = Math.min(100, (s / maxS) * 100) + '%';
      balk.setAttribute('aria-valuenow', String(Math.min(maxS, s)));
      let fase = fasen[0];
      for (const f of fasen) if (s >= f.vanaf) fase = f;
      tekst.textContent = fase.tekst + ' (' + s + ' s; maximaal ' + maxS + ' s)';
    };

    return {
      begin() {
        start = Date.now();
        wrap.hidden = false;
        tik();
        timer = setInterval(tik, 1000);
      },
      eind(slotTekst) {
        if (timer) clearInterval(timer);
        timer = null;
        if (slotTekst) {
          vul.style.width = '100%';
          tekst.textContent = slotTekst;
          setTimeout(() => { wrap.hidden = true; vul.style.width = '0%'; }, 2500);
        } else {
          wrap.hidden = true;
          vul.style.width = '0%';
        }
      }
    };
  }

  const verversVoortgang = maakVoortgang(
    'ververs-voortgang', 'ververs-balk', 'ververs-vul', 'ververs-voortgang-tekst',
    [
      { vanaf: 0, tekst: 'Opdracht verstuurd, de auto wordt wakker gemaakt…' },
      { vanaf: 15, tekst: 'Wachten op antwoord — de auto doet hier vaak een minuut over…' },
      { vanaf: 45, tekst: 'Nog steeds bezig. Dit mag tot twee minuten duren; niet nog eens drukken…' },
      { vanaf: 95, tekst: 'Bijna de maximale wachttijd van twee minuten bereikt…' }
    ]
  );

  const klimaatVoortgang = maakVoortgang(
    'klimaat-voortgang', 'klimaat-balk', 'klimaat-vul', 'klimaat-voortgang-tekst',
    [
      { vanaf: 0, tekst: 'Opdracht verstuurd naar de auto…' },
      { vanaf: 15, tekst: 'Wachten tot de auto bevestigt — dit duurt vaak een minuut…' },
      { vanaf: 45, tekst: 'Nog steeds bezig. Dit mag tot twee minuten duren; niet nog eens drukken…' },
      { vanaf: 95, tekst: 'Bijna de maximale wachttijd van twee minuten bereikt…' }
    ]
  );

  /* ── Job pollen (elke 3 s, maximaal 120 s) ───────────────── */
  async function volgJob(jobStart) {
    const job = await jobStart();
    if (!job || typeof job !== 'object') throw new ApiFout('ongeldig_antwoord', null, false, 0);
    if (job.status === 'success') return job;
    if (job.status === 'failed' || job.status === 'timeout') throw jobNaarFout(job);
    if (!job.job_id) throw new ApiFout('ongeldig_antwoord', null, false, 0);

    const begin = Date.now();
    for (;;) {
      await wacht(POLL_MS);
      if (Date.now() - begin > POLL_MAX_MS) throw new ApiFout('client_timeout', null, true, 0);
      const stand = await haalJob(job.job_id);
      if (!stand || typeof stand !== 'object') throw new ApiFout('ongeldig_antwoord', null, false, 0);
      if (stand.status === 'success') return stand;
      if (stand.status === 'failed' || stand.status === 'timeout') throw jobNaarFout(stand);
    }
  }

  /* ── Knoppen in/uit de bezig-stand ───────────────────────── */
  function zetBezig(knoppen, bezig, bezigLabel) {
    knoppen.forEach((k) => {
      if (bezig) {
        k.dataset.label = k.textContent.trim();
        k.disabled = true;
        k.setAttribute('aria-busy', 'true');
        if (bezigLabel && k === knoppen[0]) k.textContent = bezigLabel;
      } else {
        k.disabled = false;
        k.removeAttribute('aria-busy');
        if (k.dataset.label) k.textContent = k.dataset.label;
      }
    });
    if (!bezig) el('temp-min').disabled = gewensteTemp <= TEMP_MIN;
    if (!bezig) el('temp-plus').disabled = gewensteTemp >= TEMP_MAX;
  }

  /* ── Acties ──────────────────────────────────────────────── */
  let ergensBezig = false;

  async function laadAccuEnToon(stil) {
    try {
      const accu = await haalAccu();
      toonAccu(accu);
      return true;
    } catch (fout) {
      if (!stil) toonFout(fout, 'Bij het ophalen van de accustand.');
      else if (fout.code === 'unauthorized') toonFout(fout, '');
      return false;
    }
  }

  async function laadKlimaatEnToon(stil) {
    try {
      toonKlimaat(await haalKlimaat());
      return true;
    } catch (fout) {
      if (!stil) toonFout(fout, 'Bij het ophalen van de klimaatstand.');
      return false;
    }
  }

  /* Eén gemis in een los kaartje is geen reden om het hele scherm rood te
     maken: de melding blijft in de kaart zelf staan. */
  function kaartStatus(id, tekst) {
    const vak = el(id);
    if (!vak) return;
    vak.textContent = tekst || '';
    vak.className = 'kaart-status' + (tekst ? ' kaart-status--fout' : '');
    vak.hidden = !tekst;
  }

  async function laadOnderdeel(sleutel, ophalen, tonen, statusId) {
    if (!kan(sleutel)) return false;
    try {
      tonen(await ophalen());
      kaartStatus(statusId, '');
      return true;
    } catch (fout) {
      if (fout.code === 'unauthorized' || fout.httpStatus === 401) {
        toonFout(fout, '');
        return false;
      }
      kaartStatus(statusId, 'Niet opgehaald. ' + foutRegel(fout));
      return false;
    }
  }

  function laadAlles(stil) {
    return Promise.all([
      kan('battery') ? laadAccuEnToon(stil) : Promise.resolve(false),
      kan('climate') ? laadKlimaatEnToon(true) : Promise.resolve(false),
      laadOnderdeel('tyres', haalBanden, toonBanden, 'banden-status'),
      laadOnderdeel('odometer', haalKilometerstand, toonKilometerstand, 'km-status'),
      laadOnderdeel('location', haalLocatie, toonLocatie, 'locatie-status')
    ]);
  }

  async function doeVerversen() {
    if (ergensBezig) return;
    ergensBezig = true;
    meldingWeg();
    const knop = el('ververs-knop');
    zetBezig([knop], true, 'Bezig met verversen…');
    verversVoortgang.begin();
    try {
      await volgJob(startVerversen);
      verversVoortgang.eind('Verse meting binnen.');
      // Na een verse meting kunnen ook banden, kilometerstand en locatie
      // bijgewerkt zijn; die halen we er stilletjes achteraan.
      await laadAlles(false);
      meld('Verse meting opgehaald bij de auto.', 'goed');
    } catch (fout) {
      verversVoortgang.eind(null);
      toonFout(fout, 'Bij het verversen van de accustand.');
      if (fout.code === 'client_timeout') laadAccuEnToon(true);
    } finally {
      zetBezig([knop], false);
      ergensBezig = false;
    }
  }

  async function doeKlimaat(actie) {
    if (ergensBezig) return;
    ergensBezig = true;
    meldingWeg();
    const start = el('klimaat-start');
    const stop = el('klimaat-stop');
    const knoppen = actie === 'start' ? [start, stop] : [stop, start];
    zetBezig(knoppen, true, actie === 'start'
      ? 'Starten op ' + gewensteTemp + ' °C…'
      : 'Stoppen…');
    klimaatVoortgang.begin();
    try {
      await volgJob(actie === 'start' ? () => startKlimaat(gewensteTemp) : stopKlimaat);
      klimaatVoortgang.eind(actie === 'start' ? 'De auto warmt voor.' : 'Het voorverwarmen is gestopt.');
      tempAangeraakt = false;
      await laadKlimaatEnToon(true);
      meld(
        actie === 'start'
          ? 'Voorverwarmen gestart op ' + gewensteTemp + ' °C.'
          : 'Voorverwarmen gestopt.',
        'goed'
      );
    } catch (fout) {
      klimaatVoortgang.eind(null);
      toonFout(fout, actie === 'start' ? 'Bij het starten van het voorverwarmen.' : 'Bij het stoppen van het voorverwarmen.');
      laadKlimaatEnToon(true);
    } finally {
      zetBezig(knoppen, false);
      ergensBezig = false;
    }
  }

  /* ── Tokenscherm ─────────────────────────────────────────── */
  function toonTokenScherm(foutmelding) {
    el('app').hidden = true;
    const scherm = el('token-scherm');
    scherm.hidden = false;
    el('token-fout').textContent = foutmelding || '';
    const invoer = el('token-invoer');
    invoer.value = '';
    setTimeout(() => invoer.focus(), 30);
  }

  async function startApp() {
    el('token-scherm').hidden = true;
    el('app').hidden = false;
    el('menu-verbinding').textContent = opslag.duurzaam
      ? 'Token bewaard in deze browser.'
      : 'Let op: deze browser bewaart niets — na sluiten moet het token opnieuw.';

    /* Eerste aanroep: wat ondersteunt deze auto? Pas daarna wordt er iets
       getoond of opgehaald. Zo verschijnt er nooit een kaart die 403 geeft. */
    try {
      pasMogelijkhedenToe(await haalMogelijkheden());
    } catch (fout) {
      if (fout.code === 'unauthorized' || fout.httpStatus === 401) {
        toonFout(fout, '');
        return;
      }
      valMogelijkhedenTerug('code ' + fout.code);
    }

    try {
      const auto = await haalVoertuig();
      el('auto-naam').textContent = (auto && auto.nickname) || 'Ariya';
      const delen = [];
      if (auto && auto.model) delen.push(auto.model);
      if (auto && auto.vin) delen.push('VIN ' + String(auto.vin).slice(-6));
      el('auto-model').textContent = delen.join(' · ') || 'Verbonden';
    } catch (fout) {
      el('auto-model').textContent = 'Auto-gegevens niet opgehaald';
      toonFout(fout, 'Bij het ophalen van de autogegevens.');
      if (fout.code === 'unauthorized' || fout.httpStatus === 401) return;
    }

    await laadAlles(false);
  }

  /* ── Alles aan elkaar knopen ─────────────────────────────── */
  function koppel() {
    el('token-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const waarde = el('token-invoer').value.trim();
      if (!waarde) {
        el('token-fout').textContent = 'Vul het app-token in.';
        el('token-invoer').focus();
        return;
      }
      const bewaard = opslag.schrijf(waarde);
      el('token-fout').textContent = '';
      startApp();
      if (!bewaard) {
        meld('Het token kon niet bewaard worden in deze browser; het geldt alleen voor deze sessie.', 'let-op');
      }
    });

    el('token-tonen').addEventListener('change', (e) => {
      el('token-invoer').type = e.target.checked ? 'text' : 'password';
    });

    el('menu-knop').addEventListener('click', () => {
      const paneel = el('menu-paneel');
      const open = paneel.hidden;
      paneel.hidden = !open;
      el('menu-knop').setAttribute('aria-expanded', String(open));
    });

    el('token-wissen').addEventListener('click', () => {
      opslag.wis();
      el('menu-paneel').hidden = true;
      el('menu-knop').setAttribute('aria-expanded', 'false');
      meldingWeg();
      toonTokenScherm('Token gewist. Voer een token in om verder te gaan.');
    });

    el('ververs-knop').addEventListener('click', doeVerversen);
    el('klimaat-start').addEventListener('click', () => doeKlimaat('start'));
    el('klimaat-stop').addEventListener('click', () => doeKlimaat('stop'));

    el('temp-min').addEventListener('click', () => zetTemp(gewensteTemp - TEMP_STAP, false));
    el('temp-plus').addEventListener('click', () => zetTemp(gewensteTemp + TEMP_STAP, false));
    el('temp-schuif').addEventListener('input', (e) => zetTemp(parseFloat(e.target.value), false));

    el('coord-kopieer').addEventListener('click', async () => {
      if (!laatsteLocatie) return;
      const tekst = laatsteLocatie.lat.toFixed(6) + ', ' + laatsteLocatie.lon.toFixed(6);
      const knop = el('coord-kopieer');
      let gelukt = false;
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(tekst);
          gelukt = true;
        }
      } catch { gelukt = false; }
      knop.textContent = gelukt ? 'Gekopieerd' : 'Kopiëren lukt niet in deze browser';
      el('kopieer-status').textContent = gelukt
        ? 'Coördinaten gekopieerd: ' + tekst
        : 'Kopiëren lukte niet; de coördinaten staan hierboven.';
      setTimeout(() => { knop.textContent = 'Coördinaten kopiëren'; }, 2500);
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        werkLeeftijdBij();
        if (!ergensBezig && !el('app').hidden && opslag.lees()) laadAlles(true);
      }
    });
  }

  /* ── Start ───────────────────────────────────────────────── */
  koppel();
  zetTemp(21, true);
  werkLeeftijdBij();

  if (mockActief) {
    el('voet-tekst').textContent = 'DEMOSTAND (?mock=1) — er gaat niets naar een echte auto';
  }

  if (opslag.lees()) startApp();
  else toonTokenScherm('');

  /* Service worker: alleen de app-schil, nooit API-antwoorden. */
  if ('serviceWorker' in navigator && location.protocol.startsWith('http')) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('service-worker.js').catch(() => { /* niet erg */ });
    });
  }
})();
