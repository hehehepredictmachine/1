// Test 1:1 intro 3D: aplikacja ↔ wzorzec REF_C, klatka po klatce (te same chwile t).
// Użycie:
//   node update_intro3d/narzedzia/intro_1do1/porownaj.mjs --app "http://127.0.0.1:8000/?pmw_test=1#/menu"
//   node update_intro3d/narzedzia/intro_1do1/porownaj.mjs --szum
// Aplikacja w trybie testowym udostępnia: window.__PMW_TEST__.intro.seek(t) → Promise (klatka narysowana, odtwarzanie wstrzymane).
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
const here = path.dirname(fileURLToPath(import.meta.url));
const arg = k => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const APP = arg('--app'), SZUM = process.argv.includes('--szum');
const OUT = path.resolve(arg('--out') || 'update_intro3d/raport/intro_1do1'); fs.mkdirSync(OUT, { recursive: true });
const K = JSON.parse(fs.readFileSync(path.join(here, 'klatki.json'))), PROG = JSON.parse(fs.readFileSync(path.join(here, 'progi.json')));
const ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
const b = await chromium.launch({ args: ARGS });
const ctx = await b.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, locale: 'pl-PL', timezoneId: 'Europe/Warsaw' });
const PROG_PIX = 8; // = progi.piksel_rozny_gdy_kanal_rozni_sie_o
const b64 = f => 'data:image/png;base64,' + fs.readFileSync(f).toString('base64');
async function diff(a, c, out) {
  const p = await ctx.newPage(); await p.setContent('<canvas id=c></canvas>');
  const r = await p.evaluate(async ([a, c, PROG_PIX]) => {
    const ld = s => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.src = s; });
    const [A, B] = await Promise.all([ld(a), ld(c)]); const w = A.width, h = A.height;
    const g = img => { const cv = new OffscreenCanvas(w, h), x = cv.getContext('2d'); x.drawImage(img, 0, 0); return x.getImageData(0, 0, w, h).data; };
    const da = g(A), db = g(B), cv = document.getElementById('c'); cv.width = w; cv.height = h; const x = cv.getContext('2d'), o = x.createImageData(w, h);
    let bad = 0, sum = 0;
    for (let i = 0; i < da.length; i += 4) { const d = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2])); sum += d;
      const l = (da[i] + da[i + 1] + da[i + 2]) / 12; o.data[i] = o.data[i + 1] = o.data[i + 2] = l; o.data[i + 3] = 255; if (d > PROG_PIX) { bad++; o.data[i] = 255; o.data[i + 1] = 40; o.data[i + 2] = 40; } }
    x.putImageData(o, 0, 0); const n = da.length / 4; return { pct: bad / n * 100, mean: sum / n, png: cv.toDataURL() };
  }, [b64(a), b64(c), PROG_PIX]);
  fs.writeFileSync(out, Buffer.from(r.png.split(',')[1], 'base64')); await p.close(); return { pct: +r.pct.toFixed(3), mean: +r.mean.toFixed(3) };
}
let page, ok = true; const wyniki = [];
if (!SZUM) { page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(String(e)));
  await page.goto(APP); await page.waitForFunction(() => window.__PMW_TEST__?.intro?.seek, null, { timeout: 30000 }); page._errs = errs; }
for (const k of K) {
  const wz = path.join(here, 'wzorce', k.id + '.png'); let app;
  if (SZUM) app = path.join(here, 'wzorce', k.id + '__szum.png');
  else { await page.evaluate(t => window.__PMW_TEST__.intro.seek(t), k.t); await page.waitForTimeout(250); app = path.join(OUT, k.id + '__app.png'); await page.screenshot({ path: app }); }
  const r = await diff(wz, app, path.join(OUT, k.id + (SZUM ? '__szum' : '') + '__roznica.png'));
  const pass = r.pct <= PROG.rozne_piksele_proc && r.mean <= PROG.sredni_blad; ok = ok && pass;
  wyniki.push({ klatka: k.id, t: k.t, ...r, wynik: pass ? 'OK' : 'BŁĄD' }); console.log(pass ? 'OK  ' : 'BŁĄD', k.id, r.pct + '%', 'średnio ' + r.mean);
}
if (page?._errs?.length) { console.log('BŁĘDY KONSOLI', page._errs); ok = false; }
fs.writeFileSync(path.join(OUT, SZUM ? 'szum.json' : 'wynik.json'), JSON.stringify({ progi: PROG, wyniki }, null, 1));
await b.close(); process.exit(ok ? 0 : 1);
