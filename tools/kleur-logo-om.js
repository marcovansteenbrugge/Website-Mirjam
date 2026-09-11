const { chromium } = require('playwright');
const fs = require('fs');

const DOEL = [0x08, 0x2C, 0x2C]; // --teal van de site

(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const p = await b.newPage();
  await p.goto('http://localhost:8765/');

  const dataUrl = await p.evaluate(async (doel) => {
    const img = new Image();
    img.src = '/assets/images/logo.jpeg';
    await img.decode();

    const c = document.createElement('canvas');
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const beeld = ctx.getImageData(0, 0, c.width, c.height);
    const d = beeld.data;

    const lum = (r, g, bl) => 0.299 * r + 0.587 * g + 0.114 * bl;

    // Achtergrondkleur bemonsteren uit de vier hoeken.
    const hoeken = [[4, 4], [c.width - 5, 4], [4, c.height - 5], [c.width - 5, c.height - 5]];
    let sr = 0, sg = 0, sb = 0;
    for (const [x, y] of hoeken) {
      const i = (y * c.width + x) * 4;
      sr += d[i]; sg += d[i + 1]; sb += d[i + 2];
    }
    sr /= 4; sg /= 4; sb /= 4;
    const bronLum = lum(sr, sg, sb) || 1;

    for (let i = 0; i < d.length; i += 4) {
      const r = d[i], g = d[i + 1], bl = d[i + 2];

      // Hoe 'koel' is deze pixel? Blauw overheerst bij de achtergrond,
      // rood bij het goud. Daartussen wordt vloeiend gemengd, zodat
      // randen van letters en veer niet gaan rafelen.
      const w = Math.max(0, Math.min(1, (bl - r) / 45));
      if (w <= 0) continue;

      const verhouding = Math.min(2, lum(r, g, bl) / bronLum);
      for (let k = 0; k < 3; k++) {
        const nieuw = Math.min(255, doel[k] * verhouding);
        d[i + k] = d[i + k] * (1 - w) + nieuw * w;
      }
    }

    ctx.putImageData(beeld, 0, 0);
    return c.toDataURL('image/jpeg', 0.93);
  }, DOEL);

  const bytes = Buffer.from(dataUrl.split(',')[1], 'base64');
  fs.writeFileSync('/home/user/Website-Mirjam/assets/images/logo.jpeg', bytes);
  console.log('logo omgekleurd —', Math.round(bytes.length / 1024), 'KB');
  await b.close();
})();
