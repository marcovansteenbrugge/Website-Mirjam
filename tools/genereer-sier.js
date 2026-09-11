/**
 * Genereert de sierelementen van de site:
 *   assets/images/veer.svg         — donzen veer met gouden accenten en glinsters
 *   assets/images/sterrenstof.svg  — glinsterlaag voor de header
 *
 * Draaien met:  node tools/genereer-sier.js
 */
const fs = require('fs');
const path = require('path');

const BASIS = path.join(__dirname, '..', 'assets', 'images');

const W = 340, H = 480;

// Schacht: elegante S-bocht van basis (rechtsonder) naar punt (linksboven).
const P = [
  { x: 200, y: 470 },
  { x: 168, y: 340 },
  { x: 128, y: 172 },
  { x: 152, y: 14  }
];

const bez = (t) => {
  const u = 1 - t;
  return {
    x: u*u*u*P[0].x + 3*u*u*t*P[1].x + 3*u*t*t*P[2].x + t*t*t*P[3].x,
    y: u*u*u*P[0].y + 3*u*u*t*P[1].y + 3*u*t*t*P[2].y + t*t*t*P[3].y
  };
};

const raak = (t) => {
  const u = 1 - t;
  const dx = 3*u*u*(P[1].x-P[0].x) + 6*u*t*(P[2].x-P[1].x) + 3*t*t*(P[3].x-P[2].x);
  const dy = 3*u*u*(P[1].y-P[0].y) + 6*u*t*(P[2].y-P[1].y) + 3*t*t*(P[3].y-P[2].y);
  const l = Math.hypot(dx, dy);
  return { x: dx/l, y: dy/l };
};

const r1 = (n) => Math.round(n * 10) / 10;

// Deterministische ruis: elke build levert exact dezelfde veer op.
let zaad = 90218773;
const ruis = () => {
  zaad = (zaad * 1103515245 + 12345) & 0x7fffffff;
  return zaad / 0x7fffffff;
};

/* ── Baarden ─────────────────────────────────────────────────────
   Donzig effect: de baarden worden in bundels getekend. Elke bundel
   krijgt een eigen hoek en lengte, zodat er strengen ontstaan in
   plaats van een gelijkmatige kam. Ongeveer een op de vijf baarden
   is goud — die lopen als accent door het dons heen.            */

const RIJEN = 230;
const BUNDEL = 6;
const MAX = 148;
const profiel = (u) => Math.pow(Math.sin(Math.PI * Math.pow(u, 0.5)), 0.52);

const dons = [];
const goudDraden = [];
const randLinks = [], randRechts = [];

// Eigenschappen per bundel, zodat baarden binnen een bundel samen bewegen.
const bundels = [];
for (let i = 0; i <= Math.ceil(RIJEN / BUNDEL); i++) {
  bundels.push({ hoek: (ruis() - 0.5) * 0.42, lengte: 0.88 + ruis() * 0.24 });
}

for (let i = 0; i < RIJEN; i++) {
  const u = i / (RIJEN - 1);
  const t = 0.03 + u * 0.95;
  const bundel = bundels[Math.floor(i / BUNDEL)];

  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const pr = profiel(u);

  for (const kant of [-1, 1]) {
    const voller = kant < 0 ? 1 : 0.88;
    const lengte = MAX * pr * voller * bundel.lengte * (0.9 + ruis() * 0.2);
    if (lengte < 3) continue;

    // Ondiepe hoek met de schacht; bij de basis losser en donziger.
    const zwaai = 0.6 + u * 1.1 + bundel.hoek + ruis() * 0.12;
    let rx = nm.x * kant + tg.x * zwaai;
    let ry = nm.y * kant + tg.y * zwaai;
    const rl = Math.hypot(rx, ry);
    rx /= rl; ry /= rl;

    const eind = { x: p.x + rx * lengte, y: p.y + ry * lengte };
    const c1 = {
      x: p.x + nm.x * kant * lengte * 0.48 - tg.x * lengte * 0.1,
      y: p.y + nm.y * kant * lengte * 0.48 - tg.y * lengte * 0.1
    };
    const bocht = 0.16 + ruis() * 0.32;
    const c2 = {
      x: eind.x - nm.x * kant * lengte * bocht - tg.x * lengte * 0.22,
      y: eind.y - nm.y * kant * lengte * bocht - tg.y * lengte * 0.22
    };

    const d = `M${r1(p.x)} ${r1(p.y)} C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(eind.x)} ${r1(eind.y)}`;

    if (ruis() < 0.19) {
      // Gouden draad: dunner en helderder dan het dons eromheen.
      goudDraden.push(`<path d="${d}" stroke-width="${r1(0.4 + 0.45 * pr)}" opacity="${r1(0.32 + 0.45 * pr)}"/>`);
    } else {
      dons.push(`<path d="${d}" stroke-width="${r1(0.4 + 0.6 * pr)}" opacity="${r1(0.15 + 0.36 * pr)}"/>`);
    }
    (kant < 0 ? randLinks : randRechts).push(eind);
  }
}

// Losse donsbaarden bij de basis: lang, krullend en ver uit elkaar.
for (let i = 0; i < 34; i++) {
  const t = 0.03 + (i / 33) * 0.26;
  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const kant = i % 2 === 0 ? -1 : 1;
  const lengte = 20 + ruis() * 42;

  const eind = {
    x: p.x + nm.x * kant * lengte * 1.2 + tg.x * lengte * 0.15,
    y: p.y + nm.y * kant * lengte * 1.2 + tg.y * lengte * 0.15
  };
  const c1 = {
    x: p.x + nm.x * kant * lengte * 0.45 - tg.x * lengte * 0.15,
    y: p.y + nm.y * kant * lengte * 0.45 - tg.y * lengte * 0.15
  };
  const c2 = {
    x: eind.x - nm.x * kant * lengte * 0.2 - tg.x * lengte * 0.28,
    y: eind.y - nm.y * kant * lengte * 0.2 - tg.y * lengte * 0.28
  };
  const d = `M${r1(p.x)} ${r1(p.y)} C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(eind.x)} ${r1(eind.y)}`;
  (ruis() < 0.22 ? goudDraden : dons).push(
    `<path d="${d}" stroke-width="0.4" opacity="${r1(0.1 + ruis() * 0.14)}"/>`
  );
}

/* ── Contour van de vlag, voor vulling en gloed ───────────────── */
const lijn = (punten, start) =>
  punten.map((p, i) => `${i === 0 ? start : 'L'}${r1(p.x)} ${r1(p.y)}`).join(' ');
const vlagPad = lijn(randLinks, 'M') + ' ' + lijn(randRechts.slice().reverse(), 'L') + ' Z';

/* ── Schacht ─────────────────────────────────────────────────── */
const zijA = [], zijB = [];
for (let i = 0; i <= 48; i++) {
  const t = i / 48;
  const p = bez(t);
  const tg = raak(t);
  const n = { x: -tg.y, y: tg.x };
  const w = 2.3 * Math.pow(1 - t, 1.35) + 0.3;
  zijA.push(`${r1(p.x + n.x * w)} ${r1(p.y + n.y * w)}`);
  zijB.push(`${r1(p.x - n.x * w)} ${r1(p.y - n.y * w)}`);
}
const schachtPad = `M${zijA.join(' L')} L${zijB.reverse().join(' L')} Z`;

/* ── Glinsters ───────────────────────────────────────────────── */
// Vierpuntige ster met holle zijden.
const ster = (r) => {
  const k = r * 0.14;
  return `M0 ${-r} C0 ${-k} ${k} 0 ${r} 0 C${k} 0 0 ${k} 0 ${r} C0 ${k} ${-k} 0 ${-r} 0 C${-k} 0 0 ${-k} 0 ${-r} Z`;
};

const glinsters = [];
for (let i = 0; i < 18; i++) {
  const t = 0.12 + ruis() * 0.84;
  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const kant = ruis() < 0.5 ? -1 : 1;
  const afstand = ruis() * MAX * profiel((t - 0.03) / 0.95) * 0.8;

  const x = p.x + nm.x * kant * afstand + tg.x * afstand * 0.5;
  const y = p.y + nm.y * kant * afstand + tg.y * afstand * 0.5;
  const r = 3 + ruis() * 8;

  glinsters.push(
    `<g transform="translate(${r1(x)} ${r1(y)}) rotate(${Math.round(ruis() * 60 - 30)})">` +
    `<circle r="${r1(r * 1.5)}" fill="url(#glans)"/>` +
    `<path d="${ster(r1(r))}" fill="#FFF8E7"/>` +
    `<path d="${ster(r1(r * 0.45))}" fill="#FFFFFF" transform="rotate(45)" opacity="0.8"/>` +
    `</g>`
  );
}

const stof = [];
for (let i = 0; i < 80; i++) {
  const t = 0.02 + ruis() * 0.96;
  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const kant = ruis() < 0.5 ? -1 : 1;
  const afstand = ruis() * MAX * 1.2;

  const x = p.x + nm.x * kant * afstand + tg.x * afstand * 0.4;
  const y = p.y + nm.y * kant * afstand + tg.y * afstand * 0.4;
  stof.push(
    `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(0.4 + ruis() * 1.6)}" ` +
    `fill="#F0D391" opacity="${r1(0.2 + ruis() * 0.55)}"/>`
  );
}

const veerSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Donzen veer met gouden accenten">
  <title>Donzen veer</title>
  <defs>
    <linearGradient id="donsKleur" x1="0.2" y1="1" x2="0.65" y2="0">
      <stop offset="0" stop-color="#EDE3CC"/>
      <stop offset="0.4" stop-color="#FBF6EA"/>
      <stop offset="1" stop-color="#FFFFFF"/>
    </linearGradient>
    <linearGradient id="goudDraad" x1="0.2" y1="1" x2="0.7" y2="0">
      <stop offset="0" stop-color="#C79A45"/>
      <stop offset="0.4" stop-color="#EFC978"/>
      <stop offset="1" stop-color="#FFEDBE"/>
    </linearGradient>
    <linearGradient id="schachtGoud" x1="0.2" y1="1" x2="0.7" y2="0">
      <stop offset="0" stop-color="#B98F3C"/>
      <stop offset="0.45" stop-color="#EFC978"/>
      <stop offset="1" stop-color="#FFF3CF"/>
    </linearGradient>
    <radialGradient id="glans">
      <stop offset="0" stop-color="#FFF6DA" stop-opacity="0.85"/>
      <stop offset="0.35" stop-color="#E9C87A" stop-opacity="0.45"/>
      <stop offset="1" stop-color="#E9C87A" stop-opacity="0"/>
    </radialGradient>
    <filter id="wazig" x="-35%" y="-20%" width="170%" height="140%">
      <feGaussianBlur stdDeviation="11"/>
    </filter>
    <filter id="donsWaas" x="-25%" y="-15%" width="150%" height="130%">
      <feGaussianBlur stdDeviation="2.4"/>
    </filter>
    <filter id="schachtGloed" x="-60%" y="-20%" width="220%" height="140%">
      <feGaussianBlur stdDeviation="3.5"/>
    </filter>
  </defs>

  <!-- zachte gloed onder de veer; alleen vervaagd, want de contour zelf
       is grillig en zou als grijze vlek zichtbaar worden -->
  <path d="${vlagPad}" fill="#D8BE85" opacity="0.22" filter="url(#wazig)"/>

  <!-- de donsbaarden worden twee keer getekend: vervaagd voor de waas,
       daarna scherp. Via <use>, zodat de padgegevens maar één keer in
       het bestand staan. -->
  <g id="dons" fill="none" stroke="url(#donsKleur)" stroke-linecap="round">
${dons.map(d => '    ' + d).join('\n')}
  </g>
  <use href="#dons" filter="url(#donsWaas)" opacity="0.6"/>

  <!-- gouden draden die door het dons lopen -->
  <g fill="none" stroke="url(#goudDraad)" stroke-linecap="round">
${goudDraden.map(d => '    ' + d).join('\n')}
  </g>

  <!-- schacht met gloed -->
  <path d="${schachtPad}" fill="#F0D18A" opacity="0.5" filter="url(#schachtGloed)"/>
  <path d="${schachtPad}" fill="url(#schachtGoud)"/>

  <g>
${stof.map(s => '    ' + s).join('\n')}
  </g>
  <g>
${glinsters.map(g => '    ' + g).join('\n')}
  </g>
</svg>
`;

fs.writeFileSync(path.join(BASIS, 'veer.svg'), veerSvg);
console.log('veer.svg —', dons.length, 'donsbaarden,', goudDraden.length, 'gouden draden,',
            glinsters.length, 'glinsters,', Math.round(veerSvg.length / 1024), 'KB');

/* ── Losse laag gouden sterrenstof voor de header ─────────────── */
{
  const BW = 1200, BH = 440;
  const stukken = [];

  for (let i = 0; i < 150; i++) {
    const x = ruis() * BW;
    // Meer stof aan de randen dan in het midden, zodat de tekst leesbaar blijft.
    const rand = Math.abs((x / BW) - 0.5) * 2;
    if (ruis() > 0.25 + rand * 0.75) continue;
    const y = ruis() * BH;
    stukken.push(
      `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(0.5 + ruis() * 1.8)}" ` +
      `fill="#F0D391" opacity="${r1(0.2 + ruis() * 0.5)}"/>`
    );
  }

  const glans = [];
  for (let i = 0; i < 14; i++) {
    const x = ruis() * BW;
    const rand = Math.abs((x / BW) - 0.5) * 2;
    if (ruis() > 0.2 + rand * 0.8) continue;
    const y = ruis() * BH;
    const r = 3 + ruis() * 7;
    glans.push(
      `<g transform="translate(${r1(x)} ${r1(y)}) rotate(${Math.round(ruis() * 50 - 25)})">` +
      `<circle r="${r1(r * 1.6)}" fill="url(#glans)"/>` +
      `<path d="${ster(r1(r))}" fill="#FFF8E7" opacity="0.9"/>` +
      `</g>`
    );
  }

  const stofSvg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${BW} ${BH}" width="${BW}" height="${BH}" preserveAspectRatio="xMidYMid slice" role="presentation">
  <defs>
    <radialGradient id="glans">
      <stop offset="0" stop-color="#FFF6DA" stop-opacity="0.8"/>
      <stop offset="0.35" stop-color="#E9C87A" stop-opacity="0.4"/>
      <stop offset="1" stop-color="#E9C87A" stop-opacity="0"/>
    </radialGradient>
  </defs>
${stukken.map(s => '  ' + s).join('\n')}
${glans.map(g => '  ' + g).join('\n')}
</svg>
`;
  fs.writeFileSync(path.join(BASIS, 'sterrenstof.svg'), stofSvg);
  console.log('sterrenstof.svg —', stukken.length, 'stofjes,', glans.length, 'glinsters');
}
