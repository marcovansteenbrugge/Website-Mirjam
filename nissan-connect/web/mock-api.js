/* Ariya Connect — nep-backend in de browser.
   Doet alsof hij het CONTRACT.md implementeert, zodat de UI zonder server
   ontwikkeld en gedemonstreerd kan worden. Actief met ?mock=1 in de URL.

   Handige extra's in de URL:
     ?mock=1&leeftijd=185   meting is 185 minuten oud
     ?mock=1&soc=12         begin met 12% accu
     ?mock=1&laden=1        auto staat te laden
     ?mock=1&leeg=1         auto levert een paar velden niet (null)
     ?mock=1&traag=1        opdrachten duren ~25 s in plaats van ~6 s
     ?mock=1&fout=vehicle_asleep   de eerstvolgende opdracht mislukt zo
*/
(() => {
  'use strict';

  const p = new URLSearchParams(location.search);
  if (p.get('mock') !== '1') return;

  const getNum = (naam, standaard) => {
    const v = parseFloat(p.get(naam));
    return isFinite(v) ? v : standaard;
  };

  const traag = p.get('traag') === '1';
  const JOB_DUUR = { refresh: traag ? 25000 : 6000, start: traag ? 20000 : 4500, stop: traag ? 18000 : 3500 };

  /* ── Nepstaat van de auto ─────────────────────────────────── */
  const auto = {
    vin: 'SJNFAAZE0U0012345',
    nickname: 'Ariya',
    model: 'Ariya 87kWh Evolve',
    battery_capacity_kwh: 87.0
  };

  const staat = {
    soc: getNum('soc', 72),
    laden: p.get('laden') === '1',
    stekker: p.get('laden') === '1' ? true : true,
    soh: 98,
    gemeten: Date.now() - getNum('leeftijd', 42) * 60000,
    leeg: p.get('leeg') === '1',
    klimaatAan: false,
    klimaatTemp: 21.0,
    klimaatGemeten: Date.now() - getNum('leeftijd', 42) * 60000
  };

  let volgendeFout = p.get('fout') || '';
  const jobs = new Map();
  let teller = 0;

  /* Accu loopt langzaam leeg, of loopt op aan de lader. */
  setInterval(() => {
    staat.soc = staat.laden
      ? Math.min(100, staat.soc + 0.3)
      : Math.max(0, staat.soc - 0.05);
    if (staat.laden && staat.soc >= 100) staat.laden = false;
  }, 10000);

  const bereik = () => Math.round((staat.soc / 100) * 430);
  const oudMinuten = () => Math.max(0, Math.floor((Date.now() - staat.gemeten) / 60000));

  const accuPayload = () => ({
    soc_percent: Math.round(staat.soc),
    range_km: staat.leeg ? null : bereik(),
    charging: staat.leeg ? null : staat.laden,
    plugged_in: staat.stekker,
    battery_capacity_kwh: auto.battery_capacity_kwh,
    state_of_health_percent: staat.leeg ? null : staat.soh,
    updated_at: new Date(staat.gemeten).toISOString(),
    stale_minutes: oudMinuten()
  });

  const klimaatPayload = () => ({
    running: staat.klimaatAan,
    target_temp_c: staat.klimaatTemp,
    updated_at: new Date(staat.klimaatGemeten).toISOString()
  });

  /* ── Foutafhandeling zoals in het contract ────────────────── */
  const FOUT_BERICHT = {
    unauthorized: 'Dit token klopt niet.',
    nissan_auth_failed: 'Inloggen bij Nissan is niet gelukt.',
    vehicle_asleep: 'De auto reageert niet — waarschijnlijk in slaapstand.',
    rate_limited: 'Te veel opdrachten achter elkaar. Probeer het straks opnieuw.',
    not_plugged_in: 'De auto hangt niet aan de laadkabel.',
    upstream_error: 'Nissan geeft een storing terug.',
    invalid_request: 'De opdracht klopt niet.'
  };
  const HERHAALBAAR = {
    unauthorized: false, nissan_auth_failed: false, vehicle_asleep: true,
    rate_limited: true, not_plugged_in: false, upstream_error: true, invalid_request: false
  };
  const HTTP_CODE = {
    unauthorized: 401, nissan_auth_failed: 502, vehicle_asleep: 503,
    rate_limited: 429, not_plugged_in: 409, upstream_error: 502, invalid_request: 400
  };
  /* Welke fouten komen meteen terug, en welke pas als de job mislukt? */
  const METEEN = ['unauthorized', 'nissan_auth_failed', 'rate_limited', 'not_plugged_in', 'invalid_request'];

  const json = (data, status) =>
    new Response(JSON.stringify(data), {
      status: status || 200,
      headers: { 'Content-Type': 'application/json' }
    });

  const foutAntwoord = (code) =>
    json({ error: { code, message: FOUT_BERICHT[code] || 'Onbekende fout.', retryable: HERHAALBAAR[code] !== false } },
      HTTP_CODE[code] || 500);

  const jobFoutObject = (code) => ({
    code, message: FOUT_BERICHT[code] || 'Onbekende fout.', retryable: HERHAALBAAR[code] !== false
  });

  /* ── De nep-fetch ─────────────────────────────────────────── */
  async function mockFetch(pad, opties) {
    const methode = ((opties && opties.method) || 'GET').toUpperCase();
    const weg = String(pad).split('?')[0].replace(/^\.?\//, '');
    const kop = (opties && opties.headers) || {};
    const auth = kop.Authorization || kop.authorization || '';

    await vertraag(methode === 'GET' ? 220 : 420);

    /* Netwerkstoring simuleren: fetch zelf faalt. */
    if (volgendeFout === 'netwerk' && weg !== 'api/jobs') {
      volgendeFout = '';
      werkBalkBij();
      throw new TypeError('Failed to fetch (mock)');
    }

    /* Token-controle, net als de echte server. */
    const token = auth.startsWith('Bearer ') ? auth.slice(7).trim() : '';
    if (!token || token === 'fout') return foutAntwoord('unauthorized');

    if (weg === 'api/vehicle' && methode === 'GET') return json(auto);
    if (weg === 'api/battery' && methode === 'GET') return json(accuPayload());
    if (weg === 'api/climate' && methode === 'GET') return json(klimaatPayload());

    if (weg.startsWith('api/jobs/') && methode === 'GET') {
      const id = weg.slice('api/jobs/'.length);
      const job = jobs.get(id);
      if (!job) return foutAntwoord('invalid_request');
      return json(jobStand(job));
    }

    if (weg === 'api/battery/refresh' && methode === 'POST') return startJob('refresh');
    if (weg === 'api/climate/stop' && methode === 'POST') return startJob('stop');

    if (weg === 'api/climate/start' && methode === 'POST') {
      let body = {};
      try { body = JSON.parse((opties && opties.body) || '{}'); } catch { body = {}; }
      const t = body.target_temp_c;
      if (typeof t !== 'number' || t < 16 || t > 26 || Math.round(t * 2) !== t * 2) {
        return foutAntwoord('invalid_request');
      }
      return startJob('start', t);
    }

    return json({ error: { code: 'invalid_request', message: 'Onbekend adres: ' + weg, retryable: false } }, 404);
  }

  function startJob(soort, temp) {
    const fout = volgendeFout;
    if (fout && METEEN.includes(fout)) {
      volgendeFout = '';
      werkBalkBij();
      return foutAntwoord(fout);
    }
    const id = 'job_' + (++teller) + '_' + Math.random().toString(36).slice(2, 7);
    jobs.set(id, {
      id, soort, temp,
      begin: Date.now(),
      duur: JOB_DUUR[soort] || 6000,
      fout: fout || '',
      afgehandeld: false
    });
    if (fout) { volgendeFout = ''; werkBalkBij(); }
    return json({ job_id: id, status: 'pending' });
  }

  function jobStand(job) {
    const klaar = Date.now() - job.begin >= job.duur;
    if (job.fout === 'nooit') return { job_id: job.id, status: 'pending', result: null, error: null };
    if (!klaar) return { job_id: job.id, status: 'pending', result: null, error: null };

    if (job.fout === 'timeout') {
      return { job_id: job.id, status: 'timeout', result: null,
        error: { code: 'vehicle_asleep', message: FOUT_BERICHT.vehicle_asleep, retryable: true } };
    }
    if (job.fout) {
      return { job_id: job.id, status: 'failed', result: null, error: jobFoutObject(job.fout) };
    }

    if (!job.afgehandeld) {
      job.afgehandeld = true;
      if (job.soort === 'refresh') {
        staat.gemeten = Date.now();
        staat.soc = Math.max(0, Math.min(100, staat.soc + (staat.laden ? 1.2 : -0.4)));
      } else if (job.soort === 'start') {
        staat.klimaatAan = true;
        staat.klimaatTemp = job.temp;
        staat.klimaatGemeten = Date.now();
      } else if (job.soort === 'stop') {
        staat.klimaatAan = false;
        staat.klimaatGemeten = Date.now();
      }
    }
    const result = job.soort === 'refresh' ? accuPayload() : klimaatPayload();
    return { job_id: job.id, status: 'success', result, error: null };
  }

  const vertraag = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ── Balkje onderin om de mock te sturen ──────────────────── */
  const KEUZES = [
    ['', 'geen fout — alles gaat goed'],
    ['vehicle_asleep', 'auto slaapt (job mislukt)'],
    ['upstream_error', 'storing bij Nissan (job mislukt)'],
    ['rate_limited', 'te veel opdrachten (429)'],
    ['not_plugged_in', 'stekker zit er niet in (409)'],
    ['nissan_auth_failed', 'Nissan-login mislukt (502)'],
    ['invalid_request', 'opdracht ongeldig (400)'],
    ['unauthorized', 'token geweigerd (401)'],
    ['netwerk', 'server onbereikbaar'],
    ['timeout', 'job eindigt in timeout'],
    ['nooit', 'auto antwoordt nooit (90 s-limiet)']
  ];

  let keuzeVeld = null;
  const werkBalkBij = () => { if (keuzeVeld) keuzeVeld.value = volgendeFout; };

  function bouwBalk() {
    const stijl = document.createElement('style');
    stijl.textContent = `
      .mockbalk{position:fixed;left:0;right:0;bottom:0;z-index:80;
        background:#2A1A00;border-top:2px solid #FFC24D;color:#FFE6B4;
        font:600 12px/1.3 system-ui,sans-serif;padding:.5rem .6rem;
        display:flex;flex-wrap:wrap;gap:.4rem;align-items:center}
      .mockbalk[data-dicht="1"]{padding:.35rem .6rem}
      .mockbalk-titel{letter-spacing:.08em;text-transform:uppercase;margin-right:auto}
      .mockbalk select,.mockbalk button{font:inherit;min-height:34px;border-radius:8px;
        background:#12181D;color:#FFE6B4;border:1px solid #FFC24D;padding:.25rem .5rem}
      .mockbalk button{cursor:pointer}
      .mockbalk-rij{display:flex;gap:.4rem;width:100%;flex-wrap:wrap}
      .mockbalk[data-dicht="1"] .mockbalk-rij{display:none}
      body{padding-bottom:5.5rem}`;
    document.head.append(stijl);

    const balk = document.createElement('div');
    balk.className = 'mockbalk';
    balk.dataset.dicht = '0';

    const titel = document.createElement('span');
    titel.className = 'mockbalk-titel';
    titel.textContent = 'DEMOSTAND — nepdata';

    const vouw = document.createElement('button');
    vouw.type = 'button';
    vouw.textContent = 'verbergen';
    vouw.addEventListener('click', () => {
      const dicht = balk.dataset.dicht === '1';
      balk.dataset.dicht = dicht ? '0' : '1';
      vouw.textContent = dicht ? 'verbergen' : 'tonen';
    });

    const rij = document.createElement('div');
    rij.className = 'mockbalk-rij';

    const label = document.createElement('label');
    label.textContent = 'Volgende opdracht: ';
    label.setAttribute('for', 'mock-fout');

    keuzeVeld = document.createElement('select');
    keuzeVeld.id = 'mock-fout';
    KEUZES.forEach(([waarde, tekst]) => {
      const o = document.createElement('option');
      o.value = waarde; o.textContent = tekst;
      keuzeVeld.append(o);
    });
    keuzeVeld.value = volgendeFout;
    keuzeVeld.addEventListener('change', () => { volgendeFout = keuzeVeld.value; });

    const oud = document.createElement('button');
    oud.type = 'button';
    oud.textContent = 'maak meting 3 uur oud';
    oud.addEventListener('click', () => { staat.gemeten = Date.now() - 3 * 3600000; });

    const laad = document.createElement('button');
    laad.type = 'button';
    laad.textContent = 'laden aan/uit';
    laad.addEventListener('click', () => { staat.laden = !staat.laden; staat.stekker = staat.laden || staat.stekker; });

    const stekker = document.createElement('button');
    stekker.type = 'button';
    stekker.textContent = 'stekker aan/uit';
    stekker.addEventListener('click', () => { staat.stekker = !staat.stekker; if (!staat.stekker) staat.laden = false; });

    rij.append(label, keuzeVeld, oud, laad, stekker);
    balk.append(titel, vouw, rij);
    document.body.append(balk);
  }

  window.ARIYA_MOCK_FETCH = mockFetch;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bouwBalk);
  } else {
    bouwBalk();
  }
})();
