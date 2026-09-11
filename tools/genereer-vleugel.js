/**
 * Genereert assets/images/vleugel.svg — een engelenvleugel van gelaagde
 * veren, in de huisstijlkleuren. De vleugel wijst naar rechtsboven; de
 * linkervleugel op de site is dezelfde tekening, horizontaal gespiegeld.
 *
 * Draaien met:  node tools/genereer-vleugel.js
 */
const fs = require('fs');
const path = require('path');

const W = 580, H = 470;

// Voorrand van de vleugel: van de schouder (linksonder) naar de punt (rechtsboven).
const P = [
  { x: 52,  y: 330 },
  { x: 184, y: 214 },
  { x: 360, y: 108 },
  { x: 552, y: 58  }
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

let zaad = 5512377;
const ruis = () => {
  zaad = (zaad * 1103515245 + 12345) & 0x7fffffff;
  return zaad / 0x7fffffff;
};

/**
 * Eén slagveer: een spitse vorm met een gouden schacht en wat baarden.
 * @param {{x,y}} wortel  aanhechtingspunt
 * @param {{x,y}} richt   eenheidsvector waarin de veer wijst
 * @param {number} lengte
 * @param {number} breedte halve breedte van de vlag
 */
const veer = (wortel, richt, lengte, breedte, dekking, metBaarden) => {
  const p = { x: -richt.y, y: richt.x };
  const punt = { x: wortel.x + richt.x * lengte, y: wortel.y + richt.y * lengte };

  const pt = (langs, opzij) => ({
    x: r1(wortel.x + richt.x * lengte * langs + p.x * breedte * opzij),
    y: r1(wortel.y + richt.y * lengte * langs + p.y * breedte * opzij)
  });

  // Ronde punt in plaats van een scherpe: anders oogt de vleugel als een
  // waaier van messen in plaats van als veren.
  const vorm =
    `M${r1(wortel.x)} ${r1(wortel.y)} ` +
    `C${pt(0.18, 0.85).x} ${pt(0.18, 0.85).y} ${pt(0.68, 1).x} ${pt(0.68, 1).y} ${pt(0.95, 0.4).x} ${pt(0.95, 0.4).y} ` +
    `C${pt(1.04, 0.16).x} ${pt(1.04, 0.16).y} ${pt(1.04, -0.16).x} ${pt(1.04, -0.16).y} ${pt(0.95, -0.36).x} ${pt(0.95, -0.36).y} ` +
    `C${pt(0.66, -0.9).x} ${pt(0.66, -0.9).y} ${pt(0.18, -0.72).x} ${pt(0.18, -0.72).y} ${r1(wortel.x)} ${r1(wortel.y)} Z`;

  const delen = [
    `<path d="${vorm}" fill="url(#pluim)" opacity="${r1(dekking)}" ` +
      `stroke="#C9BC9B" stroke-width="0.45" stroke-opacity="${r1(dekking * 0.55)}"/>`,
    `<path d="M${r1(wortel.x)} ${r1(wortel.y)} L${r1(punt.x)} ${r1(punt.y)}" ` +
      `stroke="url(#schacht)" stroke-width="${r1(0.7 + breedte * 0.05)}" fill="none" ` +
      `opacity="${r1(dekking * 0.85)}" stroke-linecap="round"/>`
  ];

  if (metBaarden) {
    for (let i = 1; i <= 6; i++) {
      const langs = 0.14 + (i / 7) * 0.74;
      const bron = {
        x: wortel.x + richt.x * lengte * langs,
        y: wortel.y + richt.y * lengte * langs
      };
      for (const kant of [-1, 1]) {
        const l = breedte * (0.75 + ruis() * 0.5) * (1 - langs * 0.35);
        const eind = {
          x: bron.x + p.x * kant * l + richt.x * l * 0.85,
          y: bron.y + p.y * kant * l + richt.y * l * 0.85
        };
        delen.push(
          `<path d="M${r1(bron.x)} ${r1(bron.y)} L${r1(eind.x)} ${r1(eind.y)}" ` +
          `stroke="#FFFFFF" stroke-width="0.5" fill="none" opacity="${r1(dekking * 0.4)}"/>`
        );
      }
    }
  }
  return delen.join('\n    ');
};

/* ── Rijen veren ──────────────────────────────────────────────────
   Rij 0 zijn de lange slagveren; die liggen achter. Daaroverheen komen
   steeds kortere rijen, zodat de veren elkaar dakpansgewijs overlappen. */
const rijen = [
  { aantal: 19, vanaf: 0.20, tot: 0.96, lengte: [150, 300], breedte: 0.2,  inzet: 0,  dekking: 0.5, baarden: true  },
  { aantal: 21, vanaf: 0.10, tot: 0.94, lengte: [112, 215], breedte: 0.21, inzet: 18, dekking: 0.55, baarden: true  },
  { aantal: 24, vanaf: 0.04, tot: 0.84, lengte: [80,  145], breedte: 0.23, inzet: 34, dekking: 0.62, baarden: false },
  { aantal: 28, vanaf: 0.00, tot: 0.70, lengte: [50,  92 ], breedte: 0.26, inzet: 50, dekking: 0.7, baarden: false }
];

const lagen = [];

for (const rij of rijen) {
  const stukken = [];
  for (let i = 0; i < rij.aantal; i++) {
    const f = i / (rij.aantal - 1);
    const s = rij.vanaf + f * (rij.tot - rij.vanaf);

    const punt = bez(s);
    const tg = raak(s);
    const nm = { x: -tg.y, y: tg.x };   // wijst de vleugel in, naar beneden

    // Wortel ligt iets naar binnen bij de hogere rijen.
    const wortel = {
      x: punt.x + nm.x * rij.inzet,
      y: punt.y + nm.y * rij.inzet
    };

    // Richting: omlaag, en naar achteren zwaaiend richting de schouder.
    const terug = 0.3 + s * 0.95;
    let rx = nm.x - tg.x * terug;
    let ry = nm.y - tg.y * terug;
    const rl = Math.hypot(rx, ry);
    rx /= rl; ry /= rl;

    const lengte = rij.lengte[0] + (rij.lengte[1] - rij.lengte[0]) * Math.pow(f, 0.72);
    const variatie = 0.975 + ruis() * 0.05;

    stukken.push(veer(
      wortel, { x: rx, y: ry },
      lengte * variatie, lengte * rij.breedte * variatie,
      rij.dekking, rij.baarden
    ));
  }
  lagen.push(stukken);
}

/* ── Donspluisjes bij de schouder ─────────────────────────────── */
const dons = [];
for (let i = 0; i < 40; i++) {
  const s = ruis() * 0.3;
  const punt = bez(s);
  const tg = raak(s);
  const nm = { x: -tg.y, y: tg.x };
  const inzet = 8 + ruis() * 44;
  const wortel = { x: punt.x + nm.x * inzet, y: punt.y + nm.y * inzet };
  const lengte = 14 + ruis() * 34;
  const terug = 0.5 + ruis() * 0.9;
  let rx = nm.x - tg.x * terug, ry = nm.y - tg.y * terug;
  const rl = Math.hypot(rx, ry);
  const eind = { x: wortel.x + (rx/rl) * lengte, y: wortel.y + (ry/rl) * lengte };
  dons.push(
    `<path d="M${r1(wortel.x)} ${r1(wortel.y)} L${r1(eind.x)} ${r1(eind.y)}" ` +
    `stroke="#FBF6EA" stroke-width="${r1(0.5 + ruis())}" opacity="${r1(0.15 + ruis() * 0.3)}" ` +
    `stroke-linecap="round" fill="none"/>`
  );
}

/* ── Glinsters en gouden stof ─────────────────────────────────── */
const ster = (r) => {
  const k = r * 0.14;
  return `M0 ${-r} C0 ${-k} ${k} 0 ${r} 0 C${k} 0 0 ${k} 0 ${r} C0 ${k} ${-k} 0 ${-r} 0 C${-k} 0 0 ${-k} 0 ${-r} Z`;
};

const glinsters = [];
for (let i = 0; i < 14; i++) {
  const s = ruis();
  const punt = bez(s);
  const tg = raak(s);
  const nm = { x: -tg.y, y: tg.x };
  const diep = ruis() * 150;
  const x = punt.x + nm.x * diep - tg.x * diep * 0.5;
  const y = punt.y + nm.y * diep - tg.y * diep * 0.5;
  const r = 3 + ruis() * 8;
  glinsters.push(
    `<g transform="translate(${r1(x)} ${r1(y)}) rotate(${Math.round(ruis() * 60 - 30)})">` +
    `<circle r="${r1(r * 1.6)}" fill="url(#glans)"/>` +
    `<path d="${ster(r1(r))}" fill="#FFF8E7"/>` +
    `</g>`
  );
}

const stof = [];
for (let i = 0; i < 70; i++) {
  const s = ruis();
  const punt = bez(s);
  const tg = raak(s);
  const nm = { x: -tg.y, y: tg.x };
  const diep = ruis() * 220 - 30;
  const x = punt.x + nm.x * diep - tg.x * diep * 0.4;
  const y = punt.y + nm.y * diep - tg.y * diep * 0.4;
  stof.push(
    `<circle cx="${r1(x)}" cy="${r1(y)}" r="${r1(0.5 + ruis() * 1.7)}" ` +
    `fill="#F0D391" opacity="${r1(0.2 + ruis() * 0.5)}"/>`
  );
}

// Gloed die de hele vleugel volgt.
const gloedPad = (() => {
  const boven = [], onder = [];
  for (let i = 0; i <= 24; i++) {
    const s = i / 24;
    const p = bez(s);
    const tg = raak(s);
    const nm = { x: -tg.y, y: tg.x };
    boven.push(`${r1(p.x - nm.x * 10)} ${r1(p.y - nm.y * 10)}`);
    const diep = 70 + 150 * Math.pow(s, 0.8);
    onder.push(`${r1(p.x + nm.x * diep - tg.x * diep * 0.5)} ${r1(p.y + nm.y * diep - tg.y * diep * 0.5)}`);
  }
  return `M${boven.join(' L')} L${onder.reverse().join(' L')} Z`;
})();

const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Engelenvleugel">
  <title>Engelenvleugel</title>
  <defs>
    <linearGradient id="pluim" x1="0" y1="0" x2="0.4" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="0.5" stop-color="#F7F1E3"/>
      <stop offset="1" stop-color="#DCCFB2"/>
    </linearGradient>
    <linearGradient id="schacht" x1="0" y1="0" x2="0.5" y2="1">
      <stop offset="0" stop-color="#FFEDC4"/>
      <stop offset="0.5" stop-color="#E6C77E"/>
      <stop offset="1" stop-color="#B8934A"/>
    </linearGradient>
    <radialGradient id="glans">
      <stop offset="0" stop-color="#FFF6DA" stop-opacity="0.85"/>
      <stop offset="0.35" stop-color="#E9C87A" stop-opacity="0.45"/>
      <stop offset="1" stop-color="#E9C87A" stop-opacity="0"/>
    </radialGradient>
    <filter id="wazig" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur stdDeviation="16"/>
    </filter>
  </defs>

  <path d="${gloedPad}" fill="#D8BE85" opacity="0.16" filter="url(#wazig)"/>

${lagen.map((rij, i) => `  <g class="rij-${i}">\n    ${rij.join('\n    ')}\n  </g>`).join('\n')}

  <g>
    ${dons.join('\n    ')}
  </g>
  <g>
    ${stof.join('\n    ')}
  </g>
  <g>
    ${glinsters.join('\n    ')}
  </g>
</svg>
`;

fs.writeFileSync(path.join(__dirname, '..', 'assets', 'images', 'vleugel.svg'), svg);
console.log('vleugel.svg —', rijen.reduce((n, r) => n + r.aantal, 0), 'veren,',
            glinsters.length, 'glinsters,', Math.round(svg.length / 1024), 'KB');
