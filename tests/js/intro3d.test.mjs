// Intro 3D (pakiet update_intro3d, I1 §5): oś czasu i ruch postaci deterministyczne – te same wartości przy przewijaniu w przód i w tył,
// TL.duration = 13,8 s (także w LazyIntro), brak Math.random / Date.now w module sceny.
import fs from "node:fs";
import assert from "node:assert/strict";
import { makeTrack, speedAt } from "../../frontend/src/features/intro3d/motion.ts";
const dir = new URL("../../frontend/src/features/intro3d/", import.meta.url);

const tr = makeTrack({ tStop: 5.7, dur: 1.5, phase0: 0 });
const ts = Array.from({ length: 139 }, (_, i) => i * 0.1);
const fwd = ts.map((t) => tr(t)), back = [...ts].reverse().map((t) => tr(t)).reverse();
for (let i = 0; i < ts.length; i++) assert.deepEqual(fwd[i], back[i], "t=" + ts[i]);
const tr2 = makeTrack({ tStop: 5.7, dur: 1.5, phase0: 0 });
assert.deepEqual(tr2(9.6), tr(9.6));                                          // nowa instancja = ten sam wynik
assert.equal(speedAt(0, 5.7, 1.5), 1); assert.equal(speedAt(8, 5.7, 1.5), 0);  // pełny chód → zatrzymanie
assert.ok(tr(13.8).d > tr(7.3).d - 1e-6 && Math.abs(tr(13.8).d - tr(7.3).d) < 1e-6);   // po zatrzymaniu postać stoi

const intro = fs.readFileSync(new URL("intro3d.ts", dir), "utf8"), lazy = fs.readFileSync(new URL("lazyIntro.ts", dir), "utf8");
assert.match(intro, /duration: 13\.8,/);
assert.match(lazy, /const INTRO_DURATION = 13\.8;/);
for (const f of fs.readdirSync(dir).filter((f) => f.endsWith(".ts"))) {
  const src = fs.readFileSync(new URL(f, dir), "utf8").replace(/\/\/.*$/gm, "");
  assert.ok(!/Math\.random\(|Date\.now\(/.test(src), f + ": Math.random / Date.now");
}
// bryła postaci bajt w bajt z wzorca
const a = fs.readFileSync(new URL("assets/body.bin.gz", dir)), r = new URL("../../update_intro3d/referencje/kod/intro3d/src/assets/body.bin.gz", import.meta.url);
if (fs.existsSync(r)) assert.ok(a.equals(fs.readFileSync(r)), "body.bin.gz różni się od wzorca");
console.log("intro3d OK");
