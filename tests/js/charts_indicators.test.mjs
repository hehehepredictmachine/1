// CHARTS 1:1 – K2: wskaźniki ekranu (kod wzorca w chartsRender.ts) = silnik bota (engine/chartdata.indicator_series, profil M02I per TF).
// Wejście: plik JSON z test_charts_indicators.py ({tf: {bars, indicators}}). Porównanie ostatnich 200 świec, tolerancja 1e-4 (silnik zaokrągla do 1e-5).
import fs from "node:fs";
import assert from "node:assert/strict";
import { iprofVM } from "../../frontend/src/features/forex/screens/charts/chartsAdapters.ts";
const src = fs.readFileSync(new URL("../../frontend/src/features/forex/screens/charts/chartsRender.ts", import.meta.url), "utf8");
const grab = (n) => { const m = src.match(new RegExp("^function " + n + "\\(.*$", "m")); assert.ok(m, n); return m[0]; };
const F = new Function(grab("ema") + grab("rsiF") + grab("atrF") + ";return {ema,rsiF,atrF};")();
const ca = src.slice(src.indexOf("function computeAll(){"));
assert.ok(/IP\.sig==='SMA'/.test(ca) && /rsiF\(c,IP\.rsi\)/.test(ca) && /ema\(c,IP\.ema\[0\]\)/.test(ca), "computeAll używa profilu silnika");
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const TOL = 1e-4;
for (const [tf, { bars, indicators: I }] of Object.entries(data)) {
  const c = bars.map((b) => b.c), T = bars.map((b) => b.open_utc), P = iprofVM({ indicators: I });
  const cmp = (name, mine, pts) => {
    const m = new Map(pts.map((p) => [p.time, p.value])); let n = 0, mx = 0;
    mine.forEach((v, i) => { if (i < mine.length - 200 || v == null || !m.has(T[i])) return; n++; mx = Math.max(mx, Math.abs(v - m.get(T[i]))); });
    assert.ok(n >= 150, `${tf} ${name}: za mało punktów (${n})`); assert.ok(mx < TOL, `${tf} ${name}: max|Δ| ${mx}`);
    console.log(tf, name, "n", n, "max|Δ|", mx.toExponential(2));
  };
  for (const id of P.ema.filter((x) => x != null)) cmp("EMA" + id, F.ema(c, id), I.lines.find((l) => l.id === "EMA" + id).points);
  cmp("RSI" + P.rsi, F.rsiF(c, P.rsi), I.panels.rsi.points);
  const e12 = F.ema(c, 12), e26 = F.ema(c, 26), ml = c.map((_, i) => (e12[i] != null && e26[i] != null ? e12[i] - e26[i] : null));
  cmp("MACD", ml, I.panels.macd.line);
  assert.equal(P.sig, "SMA");
  const sig = ml.map((_, i) => { if (i < 8) return null; let s = 0; for (let j = i - 8; j <= i; j++) { if (ml[j] == null) return null; s += ml[j]; } return s / 9; });
  cmp("MACD signal SMA(9)", sig, I.panels.macd.signal);
  const a = F.atrF(bars.map((b) => ({ h: b.h, l: b.l, c: b.c })));
  assert.ok(Math.abs(a[a.length - 1] - I.atr14) < TOL, `${tf} ATR14`);
}
console.log("charts indicators OK");
