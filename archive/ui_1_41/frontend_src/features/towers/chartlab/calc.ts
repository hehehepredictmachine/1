// WTC PEPE 2.1 Chart Lab - pure calculations on the REAL bars of the MT5 bridge (/api/v1/candles). No synthetic data, no look-ahead:
// every value at bar i uses bars 0..i only. These are presentation layers of the chart, they never feed the engine or an order.
export type Bar = { time: number; o: number; h: number; l: number; c: number; v: number; closed: boolean };
export type Pt = { time: number; value: number };

/** Bars of /api/v1/candles -> Bar[] (bars without a UTC time are skipped: the server clock offset is not measured yet). */
export function toBars(raw: any[]): Bar[] {
  const out: Bar[] = [];
  for (const b of raw || []) {
    if (!b || !b.open_utc) continue;
    const t = Math.floor(Date.parse(b.open_utc) / 1000);
    if (!Number.isFinite(t) || ![b.o, b.h, b.l, b.c].every(Number.isFinite)) continue;
    const v = Number.isFinite(b.rv) && b.rv > 0 ? b.rv : Number.isFinite(b.tv) ? b.tv : 0;
    if (out.length && t <= out[out.length - 1].time) continue;
    out.push({ time: t, o: b.o, h: b.h, l: b.l, c: b.c, v, closed: b.closed !== false });
  }
  return out;
}
export const volumeSource = (raw: any[]) => ((raw || []).some((b) => Number.isFinite(b?.rv) && b.rv > 0) ? "real_volume" : "tick_volume");

export function heikinAshi(bars: Bar[]): Bar[] {
  const out: Bar[] = [];
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const c = (b.o + b.h + b.l + b.c) / 4;
    const o = i === 0 ? (b.o + b.c) / 2 : (out[i - 1].o + out[i - 1].c) / 2;
    out.push({ ...b, o, c, h: Math.max(b.h, o, c), l: Math.min(b.l, o, c) });
  }
  return out;
}

export function ema(bars: Bar[], n: number): Pt[] {
  const out: Pt[] = []; const k = 2 / (n + 1); let e: number | null = null; let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    if (i < n) { sum += bars[i].c; if (i === n - 1) { e = sum / n; out.push({ time: bars[i].time, value: e }); } continue; }
    e = bars[i].c * k + (e as number) * (1 - k); out.push({ time: bars[i].time, value: e });
  }
  return out;
}

export function bollinger(bars: Bar[], n: number, mult = 2): { mid: Pt[]; up: Pt[]; lo: Pt[] } {
  const mid: Pt[] = [], up: Pt[] = [], lo: Pt[] = [];
  for (let i = n - 1; i < bars.length; i++) {
    let s = 0; for (let j = i - n + 1; j <= i; j++) s += bars[j].c;
    const m = s / n; let q = 0; for (let j = i - n + 1; j <= i; j++) q += (bars[j].c - m) ** 2;
    const sd = Math.sqrt(q / n); const t = bars[i].time;
    mid.push({ time: t, value: m }); up.push({ time: t, value: m + mult * sd }); lo.push({ time: t, value: m - mult * sd });
  }
  return { mid, up, lo };
}

/** RSI (Wilder). */
export function rsi(bars: Bar[], n: number): Pt[] {
  const out: Pt[] = []; let g = 0, l = 0;
  for (let i = 1; i < bars.length; i++) {
    const d = bars[i].c - bars[i - 1].c, up = Math.max(d, 0), dn = Math.max(-d, 0);
    if (i <= n) { g += up; l += dn; if (i === n) { g /= n; l /= n; out.push({ time: bars[i].time, value: l === 0 ? 100 : 100 - 100 / (1 + g / l) }); } continue; }
    g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n;
    out.push({ time: bars[i].time, value: l === 0 ? 100 : 100 - 100 / (1 + g / l) });
  }
  return out;
}

export function macd(bars: Bar[], fast = 12, slow = 26, sig = 9): { macd: Pt[]; signal: Pt[]; hist: Pt[] } {
  const f = new Map(ema(bars, fast).map((p) => [p.time, p.value])), s = ema(bars, slow);
  const m: Pt[] = s.filter((p) => f.has(p.time)).map((p) => ({ time: p.time, value: (f.get(p.time) as number) - p.value }));
  const sg: Pt[] = []; const k = 2 / (sig + 1); let e: number | null = null; let sum = 0;
  m.forEach((p, i) => { if (i < sig) { sum += p.value; if (i === sig - 1) { e = sum / sig; sg.push({ time: p.time, value: e }); } return; } e = p.value * k + (e as number) * (1 - k); sg.push({ time: p.time, value: e }); });
  const sm = new Map(sg.map((p) => [p.time, p.value]));
  return { macd: m, signal: sg, hist: m.filter((p) => sm.has(p.time)).map((p) => ({ time: p.time, value: p.value - (sm.get(p.time) as number) })) };
}

/** ATR (Wilder). */
export function atr(bars: Bar[], n: number): Pt[] {
  const out: Pt[] = []; let a = 0;
  for (let i = 1; i < bars.length; i++) {
    const b = bars[i], pc = bars[i - 1].c;
    const tr = Math.max(b.h - b.l, Math.abs(b.h - pc), Math.abs(b.l - pc));
    if (i <= n) { a += tr; if (i === n) { a /= n; out.push({ time: b.time, value: a }); } continue; }
    a = (a * (n - 1) + tr) / n; out.push({ time: b.time, value: a });
  }
  return out;
}

/** VWAP anchored at 00:00 UTC of every day (typical price x volume). Bars with zero volume -> weight 1 (tick volume missing). */
export function vwapDaily(bars: Bar[]): Pt[] {
  const out: Pt[] = []; let day = -1, pv = 0, vv = 0;
  for (const b of bars) {
    const d = Math.floor(b.time / 86400);
    if (d !== day) { day = d; pv = 0; vv = 0; }
    const w = b.v > 0 ? b.v : 1; pv += ((b.h + b.l + b.c) / 3) * w; vv += w;
    out.push({ time: b.time, value: pv / vv });
  }
  return out;
}

// ------------------------------------------------------------------ sessions (fixed UTC hours; DST is not applied)
export type Session = "ALL" | "ASIA" | "LONDON" | "NEWYORK";
export const SESSION_HOURS: Record<Exclude<Session, "ALL">, [number, number]> = { ASIA: [0, 9], LONDON: [7, 16], NEWYORK: [12, 21] };
export const SESSION_LABEL: Record<Session, string> = { ALL: "Całe okno", ASIA: "Asia 00–09 UTC", LONDON: "London 07–16 UTC", NEWYORK: "New York 12–21 UTC" };
export function inSession(t: number, s: Session): boolean {
  if (s === "ALL") return true;
  const h = new Date(t * 1000).getUTCHours(); const [a, b] = SESSION_HOURS[s];
  return h >= a && h < b;
}
/** Bars of the LAST occurrence of the session inside the window (the most recent UTC day that has bars of that session). */
export function lastSessionBars(bars: Bar[], s: Session): Bar[] {
  if (s === "ALL") return bars;
  const sel = bars.filter((b) => inSession(b.time, s));
  if (!sel.length) return [];
  const day = Math.floor(sel[sel.length - 1].time / 86400);
  return sel.filter((b) => Math.floor(b.time / 86400) === day);
}

// ------------------------------------------------------------------ Session Volume Profile
export type Profile = { bins: { price: number; lo: number; hi: number; vol: number; up: number; down: number }[]; poc: number; vah: number; val: number;
  binSize: number; total: number; bars: number };
/** Volume of each bar spread evenly over its High-Low range (OHLC approximation - not footprint / tick data). Value Area = va share
 *  of the volume grown from the POC towards the bigger neighbour. up/down = volume of rising / falling bars (a proxy, not aggressor delta). */
export function volumeProfile(bars: Bar[], binCount = 48, va = 0.7): Profile | null {
  if (bars.length < 2) return null;
  let lo = Infinity, hi = -Infinity;
  for (const b of bars) { lo = Math.min(lo, b.l); hi = Math.max(hi, b.h); }
  if (!(hi > lo)) return null;
  const size = (hi - lo) / binCount;
  const bins = Array.from({ length: binCount }, (_, i) => ({ price: lo + size * (i + .5), lo: lo + size * i, hi: lo + size * (i + 1), vol: 0, up: 0, down: 0 }));
  let total = 0;
  for (const b of bars) {
    const w = b.v > 0 ? b.v : 1; total += w;
    const i0 = Math.min(binCount - 1, Math.floor((b.l - lo) / size)), i1 = Math.min(binCount - 1, Math.floor((b.h - lo) / size));
    const share = w / (i1 - i0 + 1);
    for (let i = i0; i <= i1; i++) { bins[i].vol += share; if (b.c >= b.o) bins[i].up += share; else bins[i].down += share; }
  }
  let p = 0; for (let i = 1; i < binCount; i++) if (bins[i].vol > bins[p].vol) p = i;
  let a = p, z = p, acc = bins[p].vol;
  while (acc < total * va && (a > 0 || z < binCount - 1)) {
    const down = a > 0 ? bins[a - 1].vol : -1, up = z < binCount - 1 ? bins[z + 1].vol : -1;
    if (up >= down) { z++; acc += bins[z].vol; } else { a--; acc += bins[a].vol; }
  }
  return { bins, poc: bins[p].price, vah: bins[z].hi, val: bins[a].lo, binSize: size, total, bars: bars.length };
}

/** Biggest price impulse: the window of `n` consecutive bars with the largest |close(last) - open(first)| (price delta, not order flow). */
export function biggestImpulse(bars: Bar[], n: number): { from: number; to: number; dir: "BUY" | "SELL"; low: number; high: number; delta: number } | null {
  if (bars.length < n || n < 1) return null;
  let best = -1, bi = -1;
  for (let i = 0; i + n <= bars.length; i++) { const d = Math.abs(bars[i + n - 1].c - bars[i].o); if (d > best) { best = d; bi = i; } }
  const w = bars.slice(bi, bi + n);
  const delta = w[w.length - 1].c - w[0].o;
  return { from: w[0].time, to: w[w.length - 1].time, dir: delta >= 0 ? "BUY" : "SELL", low: Math.min(...w.map((b) => b.l)), high: Math.max(...w.map((b) => b.h)), delta };
}

// ------------------------------------------------------------------ SMC (swing fractals + BOS / CHoCH on close)
export type SmcEvent = { time: number; kind: "BOS" | "CHoCH"; dir: "UP" | "DOWN"; level: number };
/** Swing high / low = fractal of `k` bars on each side (confirmed k bars later - no look-ahead: the swing is only used after confirmation).
 *  A close beyond the last confirmed swing = BOS in the trend direction, CHoCH when it flips the trend. */
export function smc(bars: Bar[], k = 2): { highs: Pt[]; lows: Pt[]; events: SmcEvent[] } {
  const highs: Pt[] = [], lows: Pt[] = [], events: SmcEvent[] = [];
  let lastH: Pt | null = null, lastL: Pt | null = null, trend: "UP" | "DOWN" | null = null, usedH = -1, usedL = -1;
  for (let i = 0; i < bars.length; i++) {
    const j = i - k;                               // candidate confirmed at bar i
    if (j >= k) {
      const b = bars[j]; let isH = true, isL = true;
      for (let q = j - k; q <= j + k; q++) {                   // equal highs / lows: the FIRST bar of the plateau is the swing
        if (q === j) continue;
        if (q < j ? bars[q].h >= b.h : bars[q].h > b.h) isH = false;
        if (q < j ? bars[q].l <= b.l : bars[q].l < b.l) isL = false;
      }
      if (isH) { lastH = { time: b.time, value: b.h }; highs.push(lastH); }
      if (isL) { lastL = { time: b.time, value: b.l }; lows.push(lastL); }
    }
    const c = bars[i].c;
    if (lastH && c > lastH.value && usedH !== lastH.time) { events.push({ time: bars[i].time, kind: trend === "DOWN" ? "CHoCH" : "BOS", dir: "UP", level: lastH.value }); trend = "UP"; usedH = lastH.time; }
    if (lastL && c < lastL.value && usedL !== lastL.time) { events.push({ time: bars[i].time, kind: trend === "UP" ? "CHoCH" : "BOS", dir: "DOWN", level: lastL.value }); trend = "DOWN"; usedL = lastL.time; }
  }
  return { highs, lows, events };
}
