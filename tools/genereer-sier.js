// Genereert een zachte, pluizige veer met gouden schacht en glinsters.
const fs = require('fs');

const W = 240, H = 470;

// Schacht: elegante S-bocht van basis (rechtsonder) naar punt (linksboven).
const P = [
  { x: 150, y: 462 },
  { x: 118, y: 336 },
  { x: 78,  y: 172 },
  { x: 104, y: 14  }
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

// Deterministische ruis: elke build levert dezelfde veer op.
let zaad = 4472301;
const ruis = () => {
  zaad = (zaad * 1103515245 + 12345) & 0x7fffffff;
  return zaad / 0x7fffffff;
};

const AANTAL = 132;
const MAX = 92;
const profiel = (u) => Math.pow(Math.sin(Math.PI * Math.pow(u, 0.6)), 0.72);

const baarden = [];
const randLinks = [], randRechts = [];

for (let i = 0; i < AANTAL; i++) {
  const u = i / (AANTAL - 1);
  const t = 0.03 + u * 0.95;

  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const pr = profiel(u);

  for (const kant of [-1, 1]) {
    const voller = kant < 0 ? 1 : 0.8;
    const lengte = MAX * pr * voller * (0.78 + ruis() * 0.44);
    if (lengte < 3) continue;

    // Baard waaiert opzij en zwaait sterk mee naar de punt: ondiepe, pluizige hoek.
    const zwaai = 0.65 + u * 1.05 + ruis() * 0.25;
    let rx = nm.x * kant + tg.x * zwaai;
    let ry = nm.y * kant + tg.y * zwaai;
    const rl = Math.hypot(rx, ry);
    rx /= rl; ry /= rl;

    const eind = { x: p.x + rx * lengte, y: p.y + ry * lengte };
    const c1 = {
      x: p.x + nm.x * kant * lengte * 0.5 - tg.x * lengte * 0.08,
      y: p.y + nm.y * kant * lengte * 0.5 - tg.y * lengte * 0.08
    };
    const bocht = 0.18 + ruis() * 0.3;
    const c2 = {
      x: eind.x - nm.x * kant * lengte * bocht - tg.x * lengte * 0.2,
      y: eind.y - nm.y * kant * lengte * bocht - tg.y * lengte * 0.2
    };

    baarden.push(
      `<path d="M${r1(p.x)} ${r1(p.y)} C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(eind.x)} ${r1(eind.y)}" ` +
      `stroke-width="${r1(0.35 + 0.5 * pr)}" opacity="${r1(0.14 + 0.34 * pr)}"/>`
    );
    (kant < 0 ? randLinks : randRechts).push(eind);
  }
}

// Losse donsbaarden bij de basis.
for (let i = 0; i < 26; i++) {
  const t = 0.03 + (i / 25) * 0.22;
  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const kant = i % 2 === 0 ? -1 : 1;
  const lengte = 16 + ruis() * 34;

  const eind = {
    x: p.x + nm.x * kant * lengte * 1.15 + tg.x * lengte * 0.2,
    y: p.y + nm.y * kant * lengte * 1.15 + tg.y * lengte * 0.2
  };
  const c1 = {
    x: p.x + nm.x * kant * lengte * 0.45 - tg.x * lengte * 0.5,
    y: p.y + nm.y * kant * lengte * 0.45 - tg.y * lengte * 0.5
  };
  const c2 = {
    x: eind.x - nm.x * kant * lengte * 0.12 - tg.x * lengte * 0.32,
    y: eind.y - nm.y * kant * lengte * 0.12 - tg.y * lengte * 0.32
  };
  baarden.push(
    `<path d="M${r1(p.x)} ${r1(p.y)} C${r1(c1.x)} ${r1(c1.y)} ${r1(c2.x)} ${r1(c2.y)} ${r1(eind.x)} ${r1(eind.y)}" ` +
    `stroke-width="0.45" opacity="${r1(0.1 + ruis() * 0.14)}"/>`
  );
}

/* ── Vlagcontour voor vulling en gloed ───────────────────────── */
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
  const w = 2.4 * Math.pow(1 - t, 1.35) + 0.35;
  zijA.push(`${r1(p.x + n.x * w)} ${r1(p.y + n.y * w)}`);
  zijB.push(`${r1(p.x - n.x * w)} ${r1(p.y - n.y * w)}`);
}
const schachtPad = `M${zijA.join(' L')} L${zijB.reverse().join(' L')} Z`;

/* ── Glinsters ───────────────────────────────────────────────── */
// Vierpuntige ster met holle zijden — de klassieke 'sparkle'.
const ster = (r) => {
  const k = r * 0.14;
  return `M0 ${-r} C0 ${-k} ${k} 0 ${r} 0 C${k} 0 0 ${k} 0 ${r} C0 ${k} ${-k} 0 ${-r} 0 C${-k} 0 0 ${-k} 0 ${-r} Z`;
};

const glinsters = [];
const stof = [];

// Glinsters volgen de veer: op de schacht en verspreid over de vlag.
for (let i = 0; i < 16; i++) {
  const t = 0.12 + ruis() * 0.84;
  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const kant = ruis() < 0.5 ? -1 : 1;
  const afstand = ruis() * MAX * profiel((t - 0.03) / 0.95) * 0.85;

  const x = p.x + nm.x * kant * afstand + tg.x * afstand * 0.5;
  const y = p.y + nm.y * kant * afstand + tg.y * afstand * 0.5;
  const r = 3.5 + ruis() * 9;
  const draai = Math.round(ruis() * 60 - 30);

  glinsters.push(
    `<g transform="translate(${r1(x)} ${r1(y)}) rotate(${draai})">` +
    `<circle r="${r1(r * 1.5)}" fill="url(#glans)"/>` +
    `<path d="${ster(r1(r))}" fill="#FFF8E7"/>` +
    `<path d="${ster(r1(r * 0.45))}" fill="#FFFFFF" transform="rotate(45)" opacity="0.8"/>` +
    `</g>`
  );
}

// Gouden stof: kleine puntjes rondom de veer.
for (let i = 0; i < 70; i++) {
  const t = 0.02 + ruis() * 0.96;
  const p = bez(t);
  const tg = raak(t);
  const nm = { x: -tg.y, y: tg.x };
  const kant = ruis() < 0.5 ? -1 : 1;
  const afstand = ruis() * MAX * 1.25;

  const x = p.x + nm.x * kant * afstand + tg.x * afstand * 0.4;
  const y = p.y + nm.y * kant * afstand + tg.y * afstand * 0.4;
  stof.push(
    `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(0.5 + ruis() * 1.7)}" ` +
    `fill="#F0D391" opacity="${r1(0.25 + ruis() * 0.55)}"/>`
  );
}

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Gouden veer met glinsters">
  <title>Gouden veer</title>
  <defs>
    <linearGradient id="dons" x1="0.2" y1="1" x2="0.65" y2="0">
      <stop offset="0" stop-color="#E3D6BA"/>
      <stop offset="0.4" stop-color="#F6F0E2"/>
      <stop offset="1" stop-color="#FFFFFF"/>
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
      <feGaussianBlur stdDeviation="10"/>
    </filter>
    <filter id="schachtGloed" x="-60%" y="-20%" width="220%" height="140%">
      <feGaussianBlur stdDeviation="3.5"/>
    </filter>
  </defs>

  <!-- zachte gloed onder de veer -->
  <path d="${vlagPad}" fill="#D8BE85" opacity="0.22" filter="url(#wazig)"/>
  <!-- vulling geeft de vlag massa -->
  <path d="${vlagPad}" fill="url(#dons)" opacity="0.1"/>

  <!-- baarden -->
  <g fill="none" stroke="url(#dons)" stroke-linecap="round">
${baarden.map(b => '    ' + b).join('\n')}
  </g>

  <!-- schacht met gloed -->
  <path d="${schachtPad}" fill="#F0D18A" opacity="0.55" filter="url(#schachtGloed)"/>
  <path d="${schachtPad}" fill="url(#schachtGoud)"/>

  <!-- gouden stof -->
  <g>
${stof.map(s => '    ' + s).join('\n')}
  </g>

  <!-- glinsters -->
  <g>
${glinsters.map(g => '    ' + g).join('\n')}
  </g>
</svg>
`;

fs.writeFileSync('/home/user/Website-Mirjam/assets/images/veer.svg', svg);
console.log('veer.svg —', baarden.length, 'baarden,', glinsters.length, 'glinsters,', Math.round(svg.length / 1024), 'KB');

/* ── Losse laag gouden sterrenstof voor de header ─────────────── */
{
  const BW = 1200, BH = 440;
  const stukken = [];

  for (let i = 0; i < 150; i++) {
    const x = ruis() * BW;
    // Meer stof aan de randen dan in het midden, zodat tekst leesbaar blijft.
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
  fs.writeFileSync('/home/user/Website-Mirjam/assets/images/sterrenstof.svg', stofSvg);
  console.log('sterrenstof.svg —', stukken.length, 'stofjes,', glans.length, 'glinsters');
}
