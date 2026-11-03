// Рисует сцены Shorts (1080×1920) в фирменном стиле Нейропотока.
// Вход: JSON-файл [{path, card, sub, accent, n, total, title}] — аргумент командной строки.
const { chromium } = require('playwright');
const fs = require('fs');

const C = { bg: '#0B0D17', ink: '#F4F2EC', mute: '#A9ACC4',
  ai: '#8B6CFF', code: '#3DDC97', auto: '#FFB547', mkt: '#FF6B8B' };

function flows(w, h, y0, amp, sw) {
  return `<svg style="position:absolute;inset:0" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">` +
    [C.ai, C.code, C.auto, C.mkt].map((c, i) => {
      const y = y0 + i * sw * 2.6, seg = w / 3;
      let d = `M -50 ${y}`;
      for (let k = 0; k < 4; k++) { const x = -50 + k * seg; d += ` C ${x + seg * .35} ${y - amp}, ${x + seg * .65} ${y + amp}, ${x + seg} ${y}`; }
      return `<path d="${d}" stroke="${c}" stroke-width="${sw}" fill="none" stroke-linecap="round" opacity=".85"/>`;
    }).join('') + '</svg>';
}

const esc = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;');

(async () => {
  const items = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  for (const it of items) {
    const col = C[it.accent] || C.code;
    const lines = it.card.split('\n').length;
    const size = lines >= 3 ? 104 : 124;
    const html = `<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@700;900&family=Inter:wght@500;700&family=JetBrains+Mono&display=block" rel="stylesheet">
<style>*{margin:0;padding:0;box-sizing:border-box}
body{width:1080px;height:1920px;overflow:hidden;background:${C.bg};color:${C.ink};font-family:Inter,sans-serif}
.wrap{position:absolute;inset:0;background:radial-gradient(circle at 85% 12%, ${col}40 0, transparent 45%),radial-gradient(circle at 10% 92%, #0f3b33 0, transparent 40%),${C.bg}}
.grid{position:absolute;inset:0;background-image:linear-gradient(#ffffff08 1px,transparent 1px),linear-gradient(90deg,#ffffff08 1px,transparent 1px);background-size:54px 54px}
</style></head><body><div class="wrap"><div class="grid"></div>
<div style="position:absolute;left:80px;top:150px;font-family:'JetBrains Mono',monospace;font-size:32px;color:${C.mute}">НЕЙРОПОТОК · ИИ для сестёр</div>
<div style="position:absolute;right:80px;top:150px;font-family:'JetBrains Mono',monospace;font-size:32px;color:${col}">${it.n}/${it.total}</div>
<div style="position:absolute;left:80px;right:80px;top:560px">
  <div style="width:140px;height:14px;border-radius:9px;background:${col};margin-bottom:60px"></div>
  <div style="font-family:Unbounded;font-weight:900;font-size:${size}px;line-height:1.1;white-space:pre-line">${esc(it.card)}</div>
  <div style="font-size:50px;font-weight:500;color:${C.mute};margin-top:70px;line-height:1.35">${esc(it.sub || '')}</div>
</div>
${flows(1080, 1920, 1640, 70, 16)}
</div></body></html>`;
    await page.setContent(html, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: it.path });
  }
  await browser.close();
})();
