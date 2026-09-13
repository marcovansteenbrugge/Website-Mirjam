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

  /* ── Kleine hulpjes ──────────────────────────────────────── */
  const el = (id) => document.getElementById(id);
  const wacht = (ms) => new Promise((r) => setTimeout(r, ms));
  const getal = (n, cijfers = 0) =>
    n.toLocaleString('nl-NL', { minimumFractionDigits: cijfers, maximumFractionDigits: cijfers });

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
  const haalAccu = () => api('api/battery');
  const haalKlimaat = () => api('api/climate');
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
    if (accu && typeof accu.stale_minutes === 'number' && isFinite(accu.stale_minutes)) {
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

  /* ── Accu tonen ──────────────────────────────────────────── */
  function toonAccu(accu) {
    const soc = typeof accu.soc_percent === 'number' ? accu.soc_percent : null;
    const socVak = el('soc');
    const socGetal = el('soc-getal');
    const vul = el('accu-balk-vul');

    if (soc === null) {
      socGetal.textContent = '–';
      socVak.className = 'soc soc--onbekend';
      vul.style.width = '0%';
      vul.className = 'accu-balk-vul';
      el('accu-balk-label').textContent = 'Laadstatus onbekend';
    } else {
      const begrensd = Math.max(0, Math.min(100, soc));
      socGetal.textContent = getal(soc, soc % 1 === 0 ? 0 : 1);
      socVak.className = 'soc' + (begrensd <= 15 ? ' soc--laag' : begrensd <= 35 ? ' soc--midden' : '');
      vul.style.width = begrensd + '%';
      vul.className = 'accu-balk-vul' + (begrensd <= 15 ? ' laag' : begrensd <= 35 ? ' midden' : '');
      el('accu-balk-label').textContent = 'Accu ' + getal(begrensd) + ' procent vol';
    }

    const bereikBekend = typeof accu.range_km === 'number';
    el('bereik-getal').textContent = bereikBekend ? getal(Math.round(accu.range_km)) : '–';
    el('bereik-eenheid').hidden = !bereikBekend;
    el('bereik-label').textContent = bereikBekend ? 'actieradius' : 'actieradius onbekend';

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
    if (typeof accu.state_of_health_percent === 'number') {
      soh.hidden = false;
      soh.textContent = 'Accugezondheid ' + getal(accu.state_of_health_percent) + '%';
      soh.className = 'chip ' + (accu.state_of_health_percent < 80 ? 'chip--let-op' : 'chip--stil');
    } else {
      soh.hidden = true;
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
    const temp = typeof klimaat.target_temp_c === 'number' ? Math.round(klimaat.target_temp_c) : null;
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
      await laadAccuEnToon(false);
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

    await laadAccuEnToon(false);
    await laadKlimaatEnToon(true);
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

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        werkLeeftijdBij();
        if (!ergensBezig && !el('app').hidden && opslag.lees()) laadAccuEnToon(true);
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
