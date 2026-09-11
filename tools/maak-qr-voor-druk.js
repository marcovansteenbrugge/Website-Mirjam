const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium-1194/chrome-linux/chrome' });
  const p = await b.newPage();
  await p.goto('http://localhost:8766/');
  const dataUrl = await p.evaluate(async () => {
    const img = new Image();
    img.src = '/assets/qr_code.png';
    await img.decode();
    const c = document.createElement('canvas');
    // Ruime marge (quiet zone) rondom: QR-scanners hebben die nodig.
    const marge = Math.round(img.naturalWidth * 0.12);
    c.width = img.naturalWidth + marge * 2;
    c.height = img.naturalHeight + marge * 2;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#FFFFFF';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(img, marge, marge);

    const beeld = ctx.getImageData(0, 0, c.width, c.height);
    const d = beeld.data;
    // Drempelen naar puur zwart-wit: de gouden modules worden zwart,
    // de donkere achtergrond wit. Zo is het contrast maximaal.
    for (let i = 0; i < d.length; i += 4) {
      const lum = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      const v = lum > 90 ? 0 : 255;
      d[i] = d[i + 1] = d[i + 2] = v; d[i + 3] = 255;
    }
    // De toegevoegde marge moet wit blijven.
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        if (x < marge || y < marge || x >= c.width - marge || y >= c.height - marge) {
          const i = (y * c.width + x) * 4;
          d[i] = d[i + 1] = d[i + 2] = 255;
        }
      }
    }
    ctx.putImageData(beeld, 0, 0);
    return c.toDataURL('image/png');
  });
  fs.writeFileSync('drukpreview/assets/qr_zwart.png', Buffer.from(dataUrl.split(',')[1], 'base64'));
  fs.copyFileSync('drukpreview/assets/qr_zwart.png', '/home/user/Website-Mirjam/assets/images/qr_zwart.png');
  console.log('qr_zwart.png gemaakt');
  await b.close();
})();
