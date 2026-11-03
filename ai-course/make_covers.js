// Генерирует обложки и рекламные креативы «Нейропоток» в covers/*.png.
// Запуск: node make_covers.js   (нужен playwright: npm i playwright && npx playwright install chromium)
const { chromium } = require('playwright');
const path = require('path');

const C = { bg: '#0B0D17', bg2: '#141833', ink: '#F4F2EC', mute: '#A9ACC4',
  ai: '#8B6CFF', code: '#3DDC97', auto: '#FFB547' };

const head = `<link href="https://fonts.googleapis.com/css2?family=Unbounded:wght@500;700;900&family=Inter:wght@400;600;800&display=block" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:${C.bg};color:${C.ink};font-family:Inter,sans-serif;overflow:hidden}
.u{font-family:Unbounded,sans-serif}
.wrap{position:relative;width:100%;height:100%;overflow:hidden;
 background:radial-gradient(circle at 85% 15%, #2a1f6b 0, transparent 45%),
 radial-gradient(circle at 10% 95%, #0f3b33 0, transparent 40%), ${C.bg};}
.grid{position:absolute;inset:0;background-image:linear-gradient(#ffffff08 1px,transparent 1px),linear-gradient(90deg,#ffffff08 1px,transparent 1px);background-size:48px 48px}
.flow{position:absolute;inset:0}
.pill{display:inline-block;border:2px solid currentColor;border-radius:999px;padding:.35em 1em;font-weight:600;letter-spacing:.04em}
.brand{font-family:Unbounded;font-weight:900;letter-spacing:-.02em;line-height:.95}
.grad{background:linear-gradient(90deg,${C.ai},${C.code} 55%,${C.auto});-webkit-background-clip:text;color:transparent}
.tag{font-family:'JetBrains Mono',monospace;color:${C.mute}}
</style>`;

// три «потока» — волнистые линии трёх цветов
function flows(w, h, y0, amp, opacity = 1, sw = 10) {
  const cols = [C.ai, C.code, C.auto];
  const paths = cols.map((c, i) => {
    const y = y0 + i * sw * 2.6;
    let d = `M -50 ${y}`;
    const seg = w / 3;
    for (let k = 0; k < 4; k++) {
      const x = -50 + k * seg;
      d += ` C ${x + seg * .35} ${y - amp}, ${x + seg * .65} ${y + amp}, ${x + seg} ${y}`;
    }
    return `<path d="${d}" stroke="${c}" stroke-width="${sw}" fill="none" stroke-linecap="round" opacity="${opacity}"/>`;
  }).join('');
  return `<svg class="flow" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}">${paths}</svg>`;
}

const pages = {
  avatar: [640, 640, `<div class="wrap" style="display:flex;align-items:center;justify-content:center">
    <div class="grid"></div>${flows(640, 640, 300, 70, 1, 22)}
    <div class="brand" style="position:relative;font-size:150px;background:${C.bg};padding:0 26px;border-radius:40px;line-height:1.15">
      <span class="grad">Н</span><span style="color:${C.ink}">П</span></div></div>`],

  course_cover: [1280, 720, `<div class="wrap"><div class="grid"></div>${flows(1280, 720, 560, 60, .9, 12)}
    <div style="position:absolute;left:80px;top:70px">
      <div class="tag" style="font-size:22px">Halal AI · Freya &nbsp;/&nbsp; онлайн-курс</div>
      <div class="brand" style="font-size:118px;margin-top:28px">НЕЙРО<br><span class="grad">ПОТОК</span></div>
      <div style="font-size:32px;margin-top:30px;color:${C.mute};font-weight:600">ИИ · Вайбкодинг · Автоматизация —<br><span style="color:${C.ink}">3 потока, чтобы ИИ работал на вас</span></div>
    </div></div>`],

  lead_magnet: [1280, 720, `<div class="wrap"><div class="grid"></div>${flows(1280, 720, 600, 50, .8, 10)}
    <div style="position:absolute;left:80px;top:64px;right:80px">
      <span class="pill" style="color:${C.code};font-size:24px">БЕСПЛАТНО · 3 ВЕЧЕРА</span>
      <div class="u" style="font-size:78px;font-weight:900;line-height:1.02;margin-top:34px">Свой Telegram-бот<br><span class="grad">без программиста</span></div>
      <div style="font-size:30px;margin-top:28px;color:${C.mute}">Мини-интенсив «Нейропоток»: делаем бота с ИИ<br>и запускаем его в работу — с нуля, без кода</div>
    </div></div>`],
};

const tracks = [
  ['track_1', C.ai, '01', 'ИИ-АССИСТЕНТ', 'Нейросети в работе', 'Промпты, свой ИИ-помощник,<br>тексты, таблицы, контент — в 5 раз быстрее'],
  ['track_2', C.code, '02', 'ВАЙБКОДИНГ', 'Код пишет ИИ — вы им управляете', 'Боты, сайты, мини-приложения<br>без опыта программирования'],
  ['track_3', C.auto, '03', 'АВТОМАТИЗАЦИЯ', 'Рутина работает сама', 'Заявки, оплаты, рассылки, отчёты —<br>связки n8n + Telegram + Таблицы'],
];
for (const [k, col, n, title, sub, desc] of tracks) {
  pages[k] = [1280, 720, `<div class="wrap" style="background:radial-gradient(circle at 90% 10%, ${col}33 0, transparent 50%), ${C.bg}"><div class="grid"></div>
    <div class="u" style="position:absolute;right:40px;bottom:-60px;font-size:420px;font-weight:900;color:${col};opacity:.12">${n}</div>
    <div style="position:absolute;left:80px;top:70px">
      <div class="tag" style="font-size:22px">НЕЙРОПОТОК &nbsp;/&nbsp; поток ${n}</div>
      <div class="u" style="font-size:${title.length>11?78:96}px;font-weight:900;color:${col};margin-top:40px;line-height:1">${title}</div>
      <div style="font-size:40px;font-weight:800;margin-top:30px">${sub}</div>
      <div style="font-size:28px;margin-top:22px;color:${C.mute};line-height:1.4">${desc}</div>
    </div>
    <div style="position:absolute;left:80px;bottom:60px;width:220px;height:10px;border-radius:9px;background:${col}"></div></div>`];
}

pages.ad_square = [1080, 1080, `<div class="wrap"><div class="grid"></div>${flows(1080, 1080, 900, 60, .9, 14)}
  <div style="position:absolute;left:70px;top:80px;right:70px">
    <div class="tag" style="font-size:26px">НЕЙРОПОТОК · бесплатный мини-интенсив</div>
    <div class="u" style="font-size:84px;font-weight:900;line-height:1.05;margin-top:50px">Сделайте<br>своего бота<br><span class="grad">за 3 вечера</span></div>
    <div style="font-size:36px;margin-top:40px;color:${C.mute};line-height:1.35">Код пишет ИИ.<br>Вы — ставите задачу.</div>
    <span class="pill" style="color:${C.code};font-size:30px;margin-top:44px">Забрать уроки →</span>
  </div></div>`];

pages.ad_story = [1080, 1920, `<div class="wrap"><div class="grid"></div>${flows(1080, 1920, 1640, 90, .9, 18)}
  <div style="position:absolute;left:80px;top:200px;right:80px">
    <div class="tag" style="font-size:30px">Halal AI · Freya</div>
    <div class="brand" style="font-size:132px;margin-top:40px">НЕЙРО<br><span class="grad">ПОТОК</span></div>
    <div class="u" style="font-size:64px;font-weight:700;line-height:1.15;margin-top:90px">Telegram-бот<br>без программиста —<br><span style="color:${C.code}">за 3 вечера</span></div>
    <div style="font-size:42px;margin-top:60px;color:${C.mute};line-height:1.4">Бесплатно. Без опыта.<br>ИИ пишет код — вы управляете.</div>
    <div style="margin-top:90px"><span class="pill" style="color:${C.auto};font-size:44px">Начать в боте ↑</span></div>
  </div></div>`];

pages.channel_post_header = [1280, 400, `<div class="wrap"><div class="grid"></div>${flows(1280, 400, 300, 30, .9, 9)}
  <div style="position:absolute;left:70px;top:60px"><div class="brand" style="font-size:96px">НЕЙРО<span class="grad">ПОТОК</span></div>
  <div class="tag" style="font-size:24px;margin-top:20px">ИИ · вайбкодинг · автоматизация — без хайпа</div></div></div>`];

(async () => {
  const browser = await chromium.launch();
  for (const [name, [w, h, html]] of Object.entries(pages)) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.setContent(`<!doctype html><html><head><meta charset="utf-8">${head}</head><body style="width:${w}px;height:${h}px">${html}</body></html>`, { waitUntil: 'networkidle' });
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(__dirname, 'covers', name + '.png') });
    await page.close();
    console.log('ok', name);
  }
  await browser.close();
})();
