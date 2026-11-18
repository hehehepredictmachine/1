// Test 1:1 ekranu CHARTS: aplikacja (tryb testowy) ↔ wzorzec z REF_B, na tych samych danych (fixtures/*.json).
// Użycie:
//   node update_charts/narzedzia/charts_1do1/porownaj.mjs --app "http://127.0.0.1:8000/#/forex?s=charts"   ← test aplikacji
//   node update_charts/narzedzia/charts_1do1/porownaj.mjs --szum                                            ← szum samego wzorca
// Aplikacja w trybie testowym musi udostępnić: window.__PMW_TEST__.charts.load(fixture) → Promise (gotowe po wczytaniu).
// Wynik: raport/charts_1do1/<scenariusz>__app.png, __roznica.png, wynik.json; kod wyjścia 1 przy przekroczeniu progu.
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { VCLOCK } from './vclock.mjs';
const here = path.dirname(fileURLToPath(import.meta.url));
const arg = k => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const APP = arg('--app'), SZUM = process.argv.includes('--szum');
const OUT = path.resolve(arg('--out') || 'update_charts/raport/charts_1do1'); fs.mkdirSync(OUT, { recursive: true });
const SC = JSON.parse(fs.readFileSync(path.join(here, 'scenariusze.json')));
const PROG = JSON.parse(fs.readFileSync(path.join(here, 'progi.json')));
// Obszary, w których aplikacja MOŻE się różnić (tylko teksty o pochodzeniu danych); reszta ekranu musi się zgadzać.
// Maskowany jest wyłącznie znacznik źródła danych w nagłówku (DEMO / SYNTETYCZNE / brak). Tekst notki karty planu
// w trybie testowym aplikacja bierze z fixture.test_texts.cardNote, więc karta ma tę samą wysokość i NIE jest maskowana.
const MASKI = ['#ch-right .demo-tag', '[data-pmw-1do1-maska]'];
// Obszary oceniane osobno (każdy musi zmieścić się w progu – mała zmiana w małym oknie nie „rozmyje się” w całym ekranie).
const OBSZARY = { naglowek: '#ch-head', wykres_glowny: '#charts-screen .cs-win.main', karta_planu: '#sig-card', kronos: '#kr-plot', kronos_stopka: '#kr-foot', zakladki: '#opt-tabs', opcje: '#opt-body', odczyt: '#mc-read' };
const ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
const browser = await chromium.launch({ args: ARGS });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1, timezoneId: 'Europe/Warsaw', locale: 'pl-PL', reducedMotion: 'no-preference' });
await ctx.addInitScript(VCLOCK);                 // 1.42.5: aplikacja na tym samym zegarze wirtualnym co wzorce
const b64 = f => 'data:image/png;base64,' + fs.readFileSync(f).toString('base64');
async function diff(aPng, bPng, masks, outPng, regions) {
  const p = await ctx.newPage(); await p.setContent('<canvas id=c></canvas>');
  const r = await p.evaluate(async ([a, b, masks, regions]) => {
    const ld = s => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = s; });
    const [A, B] = await Promise.all([ld(a), ld(b)]); const w = A.width, h = A.height;
    const g = (img) => { const c = new OffscreenCanvas(w, h), x = c.getContext('2d'); x.drawImage(img, 0, 0); return x.getImageData(0, 0, w, h).data; };
    const da = g(A), db = g(B), c = document.getElementById('c'); c.width = w; c.height = h; const x = c.getContext('2d'), out = x.createImageData(w, h);
    const inMask = (px, py) => masks.some(m => px >= m.l && px < m.r && py >= m.t && py < m.b);
    let bad = 0, tot = 0; const R = Object.fromEntries(Object.keys(regions).map(k => [k, { bad: 0, tot: 0 }]));
    const inR = (px, py, m) => m && px >= m.l && px < m.r && py >= m.t && py < m.b;
    for (let i = 0, k = 0; i < da.length; i += 4, k++) {
      const px = k % w, py = (k / w) | 0, lum = .3 * da[i] + .59 * da[i + 1] + .11 * da[i + 2];
      out.data[i] = out.data[i + 1] = out.data[i + 2] = lum * .25; out.data[i + 3] = 255;
      if (inMask(px, py)) { out.data[i + 2] = 90; continue; }
      tot++; const d = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2])), zle = d > 40;
      if (zle) { bad++; out.data[i] = 255; out.data[i + 1] = 40; out.data[i + 2] = 40; }
      for (const k in regions) if (inR(px, py, regions[k])) { R[k].tot++; if (zle) R[k].bad++; }
    }
    x.putImageData(out, 0, 0); const reg = {}; for (const k in R) if (R[k].tot) reg[k] = +(R[k].bad / R[k].tot * 100).toFixed(3);
    return { pct: bad / tot * 100, reg, png: c.toDataURL('image/png') };
  }, [b64(aPng), b64(bPng), masks, regions]);
  fs.writeFileSync(outPng, Buffer.from(r.png.split(',')[1], 'base64')); await p.close(); return { pct: +r.pct.toFixed(3), reg: r.reg };
}
const wyniki = []; let ok = true;
for (const s of SC) {
  const wz = path.join(here, 'wzorce', s.id + '.png'); let app, masks = [], regions = {};
  if (SZUM) app = path.join(here, 'wzorce', s.id + '__szum.png');
  else {
    const fx = JSON.parse(fs.readFileSync(path.join(here, 'fixtures', s.id + '.json')));
    const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(String(e)));
    await p.goto(APP); await p.waitForTimeout(800); await p.evaluate(() => __pmwRun(15));
    await p.waitForFunction(() => window.__PMW_TEST__?.charts?.load, null, { timeout: 30000 }); await p.evaluate(() => __pmwRun(15)); await p.waitForTimeout(1000);
    await p.evaluate(fx => { window.__PMW_TEST__.charts.load(fx); }, fx); await p.evaluate(() => __pmwRun(40)); await p.waitForTimeout(400);
    const mw = path.join(here, 'wzorce', s.id + '.maski.json'); const mWz = fs.existsSync(mw) ? JSON.parse(fs.readFileSync(mw)) : [];
    masks = mWz.concat(await p.evaluate(sel => sel.flatMap(q => [...document.querySelectorAll(q)].map(e => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; })), MASKI));
    regions = await p.evaluate(O => Object.fromEntries(Object.entries(O).map(([k, q]) => { const e = document.querySelector(q); if (!e || e.hidden) return [k, null]; const r = e.getBoundingClientRect(); return [k, r.width > 2 ? { l: r.left, t: r.top, r: r.right, b: r.bottom } : null]; }).filter(x => x[1])), OBSZARY);
    const brak = Object.keys(OBSZARY).filter(k => !(k in regions) && k !== 'karta_planu'); if (brak.length) { console.log('BRAK ELEMENTÓW (id/klasy jak w REF_B):', s.id, brak); ok = false; }
    app = path.join(OUT, s.id + '__app.png'); await p.screenshot({ path: app }); await p.close();
    if (errs.length) { console.log('BŁĘDY KONSOLI', s.id, errs); ok = false; }
  }
  const { pct, reg } = await diff(wz, app, masks, path.join(OUT, s.id + (SZUM ? '__szum' : '') + '__roznica.png'), regions);
  const zleObszary = Object.entries(reg).filter(([, v]) => v > PROG.obszar_proc).map(([k, v]) => k + ' ' + v + '%');
  const pass = pct <= PROG.ekran_proc && !zleObszary.length; ok = ok && pass;
  wyniki.push({ scenariusz: s.id, ekran_proc: pct, obszary_proc: reg, progi: PROG, wynik: pass ? 'OK' : 'BŁĄD' });
  console.log(pass ? 'OK  ' : 'BŁĄD', s.id, 'ekran ' + pct + '%', zleObszary.length ? '· przekroczone: ' + zleObszary.join(', ') : '');
}
fs.writeFileSync(path.join(OUT, SZUM ? 'szum.json' : 'wynik.json'), JSON.stringify(wyniki, null, 1));
await browser.close(); process.exit(ok ? 0 : 1);
