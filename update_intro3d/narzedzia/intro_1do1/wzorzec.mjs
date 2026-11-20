// Renderuje klatki wzorcowe intro z referencje/REF_C (na TYM komputerze – czcionki, Chromium, GPU programowy jak w teście).
// Użycie: node update_intro3d/narzedzia/intro_1do1/wzorzec.mjs
import fs from 'node:fs'; import path from 'node:path'; import { fileURLToPath, pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
const here = path.dirname(fileURLToPath(import.meta.url));
const REF = pathToFileURL(path.join(here, '../../referencje/REF_C_intro_3d_i_menu.html')).href;
const K = JSON.parse(fs.readFileSync(path.join(here, 'klatki.json'))); fs.mkdirSync(path.join(here, 'wzorce'), { recursive: true });
export const ARGS = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'];
const b = await chromium.launch({ args: ARGS });
const ctx = await b.newContext({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1, locale: 'pl-PL', timezoneId: 'Europe/Warsaw' });
const p = await ctx.newPage(); await p.goto(REF); await p.waitForFunction(() => window.PMW_PREVIEW?.intro?.readyState === 4); await p.evaluate(() => PMW_PREVIEW.intro.pause());
for (const k of K) {
  await p.evaluate(t => { PMW_PREVIEW.intro.currentTime = t; }, k.t); await p.waitForTimeout(250);
  await p.screenshot({ path: path.join(here, 'wzorce', k.id + '.png') });
  await p.evaluate(t => { PMW_PREVIEW.intro.currentTime = t; }, k.t); await p.waitForTimeout(250);
  await p.screenshot({ path: path.join(here, 'wzorce', k.id + '__szum.png') }); console.log('OK', k.id);
}
await b.close();
