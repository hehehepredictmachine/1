// Tworzy zestawy danych (fixtures/*.json) i zrzuty wzorcowe (wzorce/*.png) z referencje/REF_B.
// Uruchom: node update_charts/narzedzia/charts_1do1/wzorzec_z_ref_b.mjs   (wymaga: npm i -D playwright; npx playwright install chromium)
//   --tylko-wzorce : NIE zmienia fixtures (dane z pakietu), tylko renderuje wzorce na TYM komputerze (czcionki, Chromium).
//                    Uruchom to przed porownaj.mjs – wzorzec i aplikacja muszą być renderowane w tym samym środowisku.
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
import { VCLOCK } from './vclock.mjs';
const here = path.dirname(fileURLToPath(import.meta.url));
const REF = pathToFileURL(path.join(here, '../../referencje/REF_B_kula_forex_i_ekrany.html')).href;
const SC = JSON.parse(fs.readFileSync(path.join(here, 'scenariusze.json')));
for (const d of ['fixtures', 'wzorce']) fs.mkdirSync(path.join(here, d), { recursive: true });
const ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
const browser = await chromium.launch({ args: ARGS });
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1, timezoneId: 'Europe/Warsaw', locale: 'pl-PL' });
const VC = process.argv.includes('--tylko-wzorce');      // 1.42.5: wzorce renderowane na zegarze wirtualnym (ten sam co w porownaj.mjs)
if (VC) await ctx.addInitScript(VCLOCK);
async function openCharts(page) {
  await page.goto(REF); await page.waitForTimeout(1500);
  await page.evaluate(() => { PMW_PREVIEW._seek('forex', 1); PMW_PREVIEW._charts(1); });
  await page.waitForTimeout(1500);
}
for (const s of SC) {
  const fxPath = path.join(here, 'fixtures', s.id + '.json'); let fx;
  if (process.argv.includes('--tylko-wzorce')) fx = JSON.parse(fs.readFileSync(fxPath)); else {
  const page = await ctx.newPage();
  await openCharts(page);
  await page.click(`#ch-asset button[data-a="${s.asset}"]`); await page.waitForTimeout(300);
  await page.click(`#ch-tf button[data-tf="${s.tf}"]`); await page.waitForTimeout(300);
  await page.click(`#opt-tabs button[data-t="${s.tab}"]`); await page.waitForTimeout(1200);
  fx = await page.evaluate(() => PMW_PREVIEW._chartsDump());
  if (s.cardMin) fx.cardMin = true;
  // teksty, które w aplikacji opisują pochodzenie danych – w trybie testowym aplikacja pokazuje je z fixture (ta sama wysokość karty)
  fx.test_texts = await page.evaluate(() => ({ cardNote: document.querySelector('#sig-card .sb > .note:last-child')?.textContent ?? null, headerTag: document.querySelector('#ch-right .demo-tag')?.textContent ?? null }));
  fs.writeFileSync(fxPath, JSON.stringify(fx));
  await page.close(); }
  // wzorzec: świeża strona, ten sam zestaw danych, odczyt po ustaleniu się animacji
  const p2 = await ctx.newPage();
  if (VC) {
    await p2.goto(REF); await p2.waitForTimeout(800); await p2.evaluate(() => __pmwRun(15));
    await p2.evaluate(() => { PMW_PREVIEW._seek('forex', 1); PMW_PREVIEW._charts(1); }); await p2.evaluate(() => __pmwRun(15)); await p2.waitForTimeout(1000);
    await p2.evaluate(fx => { PMW_PREVIEW._chartsLoad(fx); }, fx); await p2.evaluate(() => __pmwRun(40)); await p2.waitForTimeout(400);
  } else { await openCharts(p2); await p2.evaluate(fx => PMW_PREVIEW._chartsLoad(fx), fx); await p2.waitForTimeout(3000); }
  await p2.screenshot({ path: path.join(here, 'wzorce', s.id + '.png') });
  const maski = await p2.evaluate(() => ['#ch-right .demo-tag'].flatMap(q => [...document.querySelectorAll(q)].map(e => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom }; })));
  fs.writeFileSync(path.join(here, 'wzorce', s.id + '.maski.json'), JSON.stringify(maski));
  if (VC) {   // szum = NIEZALEŻNY drugi przebieg (inne opóźnienia rzeczywiste), nie ten sam obraz – sprawdza determinizm całej ścieżki
    await p2.close(); const p3 = await ctx.newPage();
    await p3.goto(REF); await p3.waitForTimeout(1300); await p3.evaluate(() => __pmwRun(15));
    await p3.evaluate(() => { PMW_PREVIEW._seek('forex', 1); PMW_PREVIEW._charts(1); }); await p3.evaluate(() => __pmwRun(15)); await p3.waitForTimeout(1500);
    await p3.evaluate(fx => { PMW_PREVIEW._chartsLoad(fx); }, fx); await p3.evaluate(() => __pmwRun(40)); await p3.waitForTimeout(1100);
    await p3.screenshot({ path: path.join(here, 'wzorce', s.id + '__szum.png') }); await p3.close();
  } else { await p2.waitForTimeout(700); await p2.screenshot({ path: path.join(here, 'wzorce', s.id + '__szum.png') }); await p2.close(); }
  console.log('OK', s.id);
}
await browser.close();
