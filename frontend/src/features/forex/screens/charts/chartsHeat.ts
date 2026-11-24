// @ts-nocheck
/* CHARTS · HEATMAPA – mapa płynności w stylu Bookmap (rysowanie 2D canvas w obszarze #mc-plot). Dane wyłącznie z modelu widoku HeatVM
   (chartsAdapters.ts): archiwum arkusza MT5 bota albo arkusz dostawcy BTC. Nic nie jest dorysowywane z świec: brak kubełka = przerwa,
   brak taśmy transakcji = brak bąbli (z opisem w legendzie). Warstwy: heatmapa płynności oczekującej, najlepszy bid / ask, bąble
   transakcji (gdy źródło je ma), bieżący arkusz po prawej (COB + suma), wolumen na dole, oś ceny i czasu, celownik. */
const F9 = '9px "Helvetica Neue",Helvetica,Arial,sans-serif', F10 = '10px "Helvetica Neue",Helvetica,Arial,sans-serif';
export const HEAT_PALETTES = {
  classic: [[0, 8, 20, 48], [.2, 14, 60, 120], [.4, 24, 120, 190], [.55, 70, 190, 230], [.7, 235, 230, 90], [.85, 250, 150, 35], [1, 235, 55, 35]],
  apollo: [[0, 14, 17, 24], [.35, 60, 68, 86], [.65, 150, 158, 178], [.85, 223, 227, 235], [1, 236, 214, 150]],
};
const LUTS = {};
export function heatLut(pal) {
  if (LUTS[pal]) return LUTS[pal];
  const st = HEAT_PALETTES[pal] || HEAT_PALETTES.classic, out = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i++) {
    const v = i / 255;
    let k = 0;
    while (k < st.length - 2 && v > st[k + 1][0]) k++;
    const a = st[k], b = st[k + 1], f = Math.max(0, Math.min(1, (v - a[0]) / (b[0] - a[0] || 1)));
    for (let c = 0; c < 3; c++) out[i * 3 + c] = Math.round(a[c + 1] + (b[c + 1] - a[c + 1]) * f);
  }
  return (LUTS[pal] = out);
}
/** jasność komórki 0..1: q / ref · wzmocnienie (ref = 97. percentyl okna; większe ściany = pełna skala) */
export const heatLevel = (q, ref, gain) => Math.max(0, Math.min(1, q / (ref || 1) * gain));
const rgb = (lut, v, a = 1) => { const i = Math.round(Math.max(0, Math.min(1, v)) * 255) * 3; return `rgba(${lut[i]},${lut[i + 1]},${lut[i + 2]},${a})`; };
const rowOf = (p, row) => Math.floor(p / row + 1e-9) * row;

/** Obraz heatmapy w przestrzeni (kolumna siatki × wiersz ceny) – jeden piksel na komórkę, skalowany przy rysowaniu bez wygładzania. */
function buildImage(H, pal, gain) {
  let lo = Infinity, hi = -Infinity;
  for (const c of H.cols) for (const [p] of c.cells) { if (p < lo) lo = p; if (p > hi) hi = p; }
  if (!isFinite(lo) || !(H.row > 0) || !(H.step > 0)) return null;
  const rows = Math.round((hi - lo) / H.row) + 1, i0 = Math.round(H.t0 / H.step), ncols = Math.max(1, Math.round((H.t1 - H.t0) / H.step));
  if (rows > 6000) return null;
  const cv = document.createElement('canvas'); cv.width = ncols; cv.height = rows;
  const g = cv.getContext('2d'), img = g.createImageData(ncols, rows), lut = heatLut(pal);
  /* fill: arkusz dostawcy odpytywany rzadziej niż kubełek – kolumna trwa do następnej (najwyżej `fill` kubełków); MT5: 1 (przerwa = brak zapisu) */
  const xs = H.cols.map((c) => Math.round(c.t / H.step) - i0);
  H.cols.forEach((c, n) => {
    const x = xs[n], x2 = Math.min(ncols, x + Math.max(1, Math.min(H.fill || 1, (n + 1 < xs.length ? xs[n + 1] : x + 1) - x)));
    if (x < 0 || x >= ncols) return;
    for (const [p, q] of c.cells) {
      const y = rows - 1 - Math.round((p - lo) / H.row); if (y < 0 || y >= rows) continue;
      const v = heatLevel(q, H.ref, gain), k = Math.round(v * 255) * 3;
      for (let xx = x; xx < x2; xx++) { const j = (y * ncols + xx) * 4; img.data[j] = lut[k]; img.data[j + 1] = lut[k + 1]; img.data[j + 2] = lut[k + 2]; img.data[j + 3] = 255; }
    }
  });
  g.putImageData(img, 0, 0);
  return { cv, lo, hi, rows, ncols };
}
const NICE_T = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200].map((s) => s * 1000);

/** st: stan widoku (yMin / yMax / obraz w pamięci, zoom, pan); o: opcje L.*; fx: fmtP, niceStep, tzShift. Zwraca geometrię i odczyt celownika. */
export function drawHeat(ctx, R0, H, st, o, fx) {
  const lut = heatLut(o.pal), uiA = o.uiA;
  const axW = 74, cobW = o.cob ? 132 : 0, taH = 22;
  const R = { l: R0.l, r: R0.r - axW - cobW, t: R0.t + 6, b: R0.b - taH };
  const volH = o.vol ? Math.min(64, (R.b - R.t) * .14) : 0, priceB = R.b - (volH ? volH + 6 : 0);
  ctx.save(); ctx.beginPath(); ctx.rect(R0.l, R0.t, R0.w, R0.h); ctx.clip(); ctx.font = F10; ctx.textBaseline = 'middle';
  ctx.strokeStyle = 'rgba(43,48,59,.9)'; ctx.beginPath(); ctx.moveTo(R.r + cobW + .5, R.t); ctx.lineTo(R.r + cobW + .5, R.b); ctx.moveTo(R.l, R.b + .5); ctx.lineTo(R.r + cobW, R.b + .5); ctx.stroke();
  const empty = (t1, t2) => { ctx.globalAlpha = uiA; ctx.fillStyle = '#898b91'; ctx.textAlign = 'center'; ctx.font = F9; ctx.fillText(t1, (R.l + R.r) / 2, (R.t + priceB) / 2 - 8);
    if (t2) { ctx.fillStyle = '#63666c'; ctx.fillText(t2, (R.l + R.r) / 2, (R.t + priceB) / 2 + 10); } ctx.globalAlpha = 1; ctx.restore(); return { R, priceB, hover: null }; };
  if (!H) return empty('Ł A D O W A N I E   A R K U S Z A', o.asset === 'BTC' ? 'arkusz dostawcy BTC – historia od otwarcia widoku' : 'archiwum arkusza MT5 bota');
  if (!H.cols.length) return empty(H.status === 'ERROR' ? 'B Ł Ą D   Ź R Ó D Ł A   A R K U S Z A' : 'B R A K   D A N Y C H   A R K U S Z A', H.reason || '');
  /* czas: okno siatki + 6 % miejsca po prawej na bieżący arkusz; przesuw płynny między odpytaniami (najwyżej o 6 s) */
  const live = Math.min(6000, Math.max(0, o.elapsed || 0)), win = H.t1 - H.t0, tNow = H.now + live, tEnd = tNow + win * .06, tStart = tEnd - win * 1.06;
  const X = (t) => R.l + (t - tStart) / (tEnd - tStart) * (R.r - R.l);
  /* cena: środek = bieżący mid (albo przesunięcie użytkownika), zakres z bid / ask okna, zoom kółkiem */
  const last = H.cols[H.cols.length - 1], d = H.dom;
  const bb = d && d.bids[0] ? d.bids[0][0] : last.bid, ba = d && d.asks[0] ? d.asks[0][0] : last.ask, mid = bb != null && ba != null ? (bb + ba) / 2 : (last.cells[0] || [0])[0];
  let lo = Infinity, hi = -Infinity;
  for (const c of H.cols) { if (c.bid != null) lo = Math.min(lo, c.bid); if (c.ask != null) hi = Math.max(hi, c.ask); }
  if (!isFinite(lo) || !isFinite(hi)) { lo = mid; hi = mid; }
  lo = Math.min(lo, bb ?? lo, mid); hi = Math.max(hi, ba ?? hi, mid);                 /* całe okno + bieżąca cena widoczne bez zoomu */
  const half = (Math.max(hi - lo, H.row * 12) * .55 + H.row * 4) * o.zoom, cen = Math.max(mid - half * .7, Math.min(mid + half * .7, (lo + hi) / 2)) + o.pan,   /* bieżąca cena zawsze w środkowych 70 % */
    k = st.yMin == null ? 1 : 1 - Math.exp(-o.dt * 8);
  st.yMin = st.yMin == null ? cen - half : st.yMin + (cen - half - st.yMin) * k; st.yMax = st.yMax == null ? cen + half : st.yMax + (cen + half - st.yMax) * k;
  const Y = (p) => R.t + (st.yMax - p) / (st.yMax - st.yMin) * (priceB - R.t), rowPx = Math.abs(Y(0) - Y(H.row));
  /* heatmapa (obraz w pamięci; przebudowa po nowych danych / palecie / kontraście) */
  const key = H.now + '|' + o.pal + '|' + o.gain;
  if (st.imgKey !== key) { st.img = buildImage(H, o.pal, o.gain); st.imgKey = key; }
  ctx.save(); ctx.beginPath(); ctx.rect(R.l, R.t, R.r - R.l, priceB - R.t); ctx.clip(); ctx.globalAlpha = uiA;
  const I = st.img;
  if (I) { ctx.imageSmoothingEnabled = false; const yTop = Y(I.hi + H.row), yBot = Y(I.lo); ctx.drawImage(I.cv, 0, 0, I.ncols, I.rows, X(H.t0), yTop, X(H.t1) - X(H.t0), yBot - yTop); ctx.imageSmoothingEnabled = true; }
  /* bieżący arkusz przedłużony w prawo od linii „teraz” (jak projekcja COB) */
  const xNow = X(tNow);
  if (d) for (const [p, q] of [...d.bids, ...d.asks]) { const r = rowOf(p, H.row), y0 = Y(r + H.row), y1 = Y(r); ctx.fillStyle = rgb(lut, heatLevel(q, H.ref, o.gain), .85); ctx.fillRect(xNow, y0, R.r - xNow, Math.max(1, y1 - y0)); }
  /* siatka: czas co „ładny” krok, cena co niceStep */
  const dtT = NICE_T.find((s) => s >= (tEnd - tStart) / Math.max(1, (R.r - R.l) / 110)) || 7200000;
  if (o.grid) { ctx.strokeStyle = 'rgba(220,226,236,.16)'; ctx.setLineDash([2, 4]); ctx.beginPath(); for (let t = Math.ceil(tStart / dtT) * dtT; t < tEnd; t += dtT) { const x = Math.round(X(t)) + .5; ctx.moveTo(x, R.t); ctx.lineTo(x, priceB); } ctx.stroke(); ctx.setLineDash([]); }
  /* najlepszy bid / ask (linie schodkowe z ostatniego snapshotu kubełka) */
  if (o.bbo) for (const [f, col] of [['bid', 'rgba(150,230,180,.95)'], ['ask', 'rgba(240,150,150,.95)']]) {
    ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.beginPath(); let pe = null;
    for (const c of H.cols) { const v = c[f]; if (v == null) { pe = null; continue; } const y = Y(v); if (pe !== c.t) ctx.moveTo(X(c.t), y); else ctx.lineTo(X(c.t), y); ctx.lineTo(X(c.t1), y); pe = c.t1; }
    if (pe != null && d && (f === 'bid' ? bb : ba) != null) ctx.lineTo(xNow, Y(f === 'bid' ? bb : ba));
    ctx.stroke(); ctx.lineWidth = 1;
  }
  /* bąble transakcji: suma wolumenu kubełka × wiersza; udział BUY / SELL jako wycinki, nieznana strona = neutralny */
  let bubbleN = 0;
  if (o.bub && H.bubbles.length) {
    const agg = new Map();
    for (const b of H.bubbles) { const i = Math.floor(b.t / H.step), r = rowOf(b.p, H.row), kk = i + '|' + r; let a = agg.get(kk); if (!a) agg.set(kk, a = { t: (i + .5) * H.step, p: r + H.row / 2, BUY: 0, SELL: 0, UNKNOWN: 0, q: 0 }); a[b.side] += b.q; a.q += b.q; }
    const all = [...agg.values()], qs = all.map((a) => a.q).sort((x, y) => x - y), qref = qs[Math.floor(.95 * (qs.length - 1))] || 1;
    for (const a of all) {
      const x = X(a.t), y = Y(a.p); if (x < R.l - 20 || x > xNow + 4 || y < R.t - 20 || y > priceB + 20) continue;
      const rad = Math.max(2.5, Math.min(24, 2.5 + 14 * Math.sqrt(a.q / qref))); let ang = -Math.PI / 2; bubbleN++;
      for (const [s, c1] of [['BUY', '96,200,140'], ['SELL', '222,92,92'], ['UNKNOWN', '214,220,232']]) {
        if (!a[s]) continue; const span = a[s] / a.q * Math.PI * 2, g = ctx.createRadialGradient(x - rad * .35, y - rad * .35, rad * .1, x, y, rad);
        g.addColorStop(0, `rgba(${c1},.95)`); g.addColorStop(1, `rgba(${c1},.55)`); ctx.fillStyle = g; ctx.beginPath();
        if (span >= Math.PI * 2 - 1e-6) ctx.arc(x, y, rad, 0, Math.PI * 2); else { ctx.moveTo(x, y); ctx.arc(x, y, rad, ang, ang + span); ctx.closePath(); }
        ctx.fill(); ang += span;
      }
      ctx.strokeStyle = 'rgba(3,4,8,.55)'; ctx.beginPath(); ctx.arc(x, y, rad, 0, Math.PI * 2); ctx.stroke();
    }
  }
  /* linia „teraz” */
  ctx.strokeStyle = 'rgba(236,239,245,.55)'; ctx.setLineDash([3, 3]); ctx.beginPath(); ctx.moveTo(Math.round(xNow) + .5, R.t); ctx.lineTo(Math.round(xNow) + .5, priceB); ctx.stroke(); ctx.setLineDash([]);
  ctx.restore();
  /* oś czasu */
  ctx.globalAlpha = uiA; ctx.fillStyle = 'rgba(137,139,145,1)'; ctx.textAlign = 'center'; ctx.font = F10;
  const pad = (n) => String(n).padStart(2, '0'), fT = (t, s) => { const z = new Date(t + fx.tzShift()); return pad(z.getUTCHours()) + ':' + pad(z.getUTCMinutes()) + (s ? ':' + pad(z.getUTCSeconds()) : ''); };
  for (let t = Math.ceil(tStart / dtT) * dtT; t < tEnd; t += dtT) { const x = X(t); if (x > R.l + 20 && x < R.r - 20) ctx.fillText(fT(t, dtT < 60000), x, R.b + 12); }
  /* oś ceny */
  const stp = fx.niceStep((st.yMax - st.yMin) / 7); ctx.textAlign = 'left';
  for (let v = Math.ceil(st.yMin / stp) * stp; v < st.yMax; v += stp) { const y = Math.round(Y(v)) + .5; if (y < R.t || y > priceB) continue;
    if (o.grid) { ctx.strokeStyle = 'rgba(200,210,230,.05)'; ctx.beginPath(); ctx.moveTo(R.l, y); ctx.lineTo(R.r, y); ctx.stroke(); }
    ctx.fillStyle = 'rgba(137,139,145,1)'; ctx.fillText(fx.fmtP(v), R.r + cobW + 10, y); }
  /* wolumen */
  if (volH) {
    const v0 = priceB + 6, vb = R.b - 1; ctx.strokeStyle = 'rgba(43,48,59,.9)'; ctx.beginPath(); ctx.moveTo(R.l, v0 - 3.5); ctx.lineTo(R.r, v0 - 3.5); ctx.stroke();
    let bars = [];
    if (H.src === 'MT5') bars = H.bars.filter((b) => b.t + 60000 > tStart).map((b) => ({ t0: b.t, t1: b.t + 60000, v: b.v, up: b.c >= b.o }));
    else { const m = new Map(); for (const b of H.bubbles) { const i = Math.floor(b.t / H.step); const a = m.get(i) || { t0: i * H.step, t1: (i + 1) * H.step, v: 0, up: null }; a.v += b.q; m.set(i, a); } bars = [...m.values()]; }
    const vmax = Math.max(1e-9, ...bars.map((b) => b.v));
    for (const b of bars) { const x0 = Math.max(R.l, X(b.t0)), x1 = Math.min(xNow, X(b.t1)); if (x1 <= x0) continue; const h = b.v / vmax * (vb - v0);
      ctx.fillStyle = b.up == null ? 'rgba(214,220,232,.35)' : b.up ? 'rgba(150,230,180,.45)' : 'rgba(240,150,150,.45)'; ctx.fillRect(x0 + .5, vb - h, Math.max(1, x1 - x0 - 1), h); }
    ctx.font = F9; ctx.fillStyle = 'rgba(137,139,145,.9)'; ctx.textAlign = 'left';
    ctx.fillText(H.src === 'MT5' ? 'TICK VOLUME M1 · aktywność kwotowań brokera, nie wolumen transakcji' : (H.trades.status === 'READY' ? 'WOLUMEN TRANSAKCJI' : 'WOLUMEN TRANSAKCJI · strona agresora niezweryfikowana'), R.l + 6, v0 + 6);
    if (!bars.length) { ctx.textAlign = 'center'; ctx.fillText('brak danych wolumenu', (R.l + R.r) / 2, (v0 + vb) / 2 + 4); }
  }
  /* bieżący arkusz (COB) + suma od najlepszej ceny */
  if (cobW && d) {
    const cl = R.r + 1, cw1 = Math.round(cobW * .56), cr = R.r + cobW; ctx.fillStyle = 'rgba(2,3,6,.86)'; ctx.fillRect(cl, R.t, cobW - 1, priceB - R.t);
    ctx.strokeStyle = 'rgba(43,48,59,.9)'; ctx.beginPath(); ctx.moveTo(cl + cw1 + .5, R.t); ctx.lineTo(cl + cw1 + .5, priceB); ctx.stroke();
    const vis = (p) => { const y = Y(rowOf(p, H.row)); return y >= R.t && y <= priceB + rowPx; };
    const side = (lv, col, cum) => { let s = 0; return lv.map(([p, q]) => { s += q; return { p, q, s, col, cum }; }); };
    const L2 = [...side(d.bids, '150,230,180'), ...side(d.asks, '240,150,150')], qmax = Math.max(...L2.filter((x) => vis(x.p)).map((x) => x.q), 1e-9), smax = Math.max(...L2.filter((x) => vis(x.p)).map((x) => x.s), 1e-9);
    const fq = (v) => v >= 100 ? Math.round(v).toLocaleString('pl-PL') : v >= 10 ? v.toFixed(1) : v.toFixed(2);
    ctx.save(); ctx.beginPath(); ctx.rect(cl, R.t, cobW, priceB - R.t); ctx.clip();
    for (const x of L2) {
      if (!vis(x.p)) continue; const r = rowOf(x.p, H.row), y0 = Y(r + H.row), y1 = Y(r), hh = Math.max(1, y1 - y0 - (rowPx > 4 ? 1 : 0));
      ctx.fillStyle = `rgba(${x.col},.5)`; ctx.fillRect(cl + 2, y0, Math.max(1, (cw1 - 4) * x.q / qmax), hh);
      ctx.fillStyle = `rgba(${x.col},.16)`; ctx.fillRect(cl + cw1 + 2, y0, Math.max(1, (cobW - cw1 - 4) * x.s / smax), hh);
      if (rowPx >= 9) { ctx.font = `${Math.min(10, Math.floor(rowPx - 1))}px "Helvetica Neue",Helvetica,Arial,sans-serif`; ctx.textAlign = 'right'; ctx.fillStyle = '#f2f2ef';
        ctx.fillText(fq(x.q), cl + cw1 - 4, (y0 + y1) / 2); ctx.fillStyle = `rgba(${x.col},1)`; ctx.fillText(fq(x.s), cr - 5, (y0 + y1) / 2); }
    }
    ctx.restore();
    ctx.font = F9; ctx.textAlign = 'center'; ctx.fillStyle = '#030408'; ctx.fillRect(cl, R.t, cobW - 1, 14); ctx.fillStyle = 'rgba(157,160,168,1)';
    ctx.fillText('COB', cl + cw1 / 2, R.t + 7); ctx.fillText('Σ OD BID / ASK', cl + cw1 + (cobW - cw1) / 2, R.t + 7);
  } else if (cobW) { ctx.font = F9; ctx.fillStyle = '#63666c'; ctx.textAlign = 'center'; ctx.fillText('BRAK ARKUSZA', R.r + cobW / 2, (R.t + priceB) / 2); }
  /* etykiety bid / ask na osi */
  ctx.font = F10; ctx.textAlign = 'left';
  const yA = ba != null ? Y(ba) : null, yB = bb != null ? Y(bb) : null, sep = yA != null && yB != null && yB - yA < 21 ? (21 - (yB - yA)) / 2 : 0;   /* małe spready: etykiety rozsunięte */
  for (const [v, col, yy] of [[ba, '#e0b3b3', yA != null ? yA - sep : null], [bb, '#cfe8da', yB != null ? yB + sep : null]]) { if (v == null) continue; const y = Math.round(yy) + .5; if (y < R.t || y > priceB) continue;
    ctx.fillStyle = '#06080c'; ctx.fillRect(R.r + cobW + 1, y - 10, axW - 2, 20); ctx.strokeStyle = col; ctx.strokeRect(R.r + cobW + 1.5, y - 9.5, axW - 3, 19); ctx.fillStyle = col; ctx.fillText(fx.fmtP(v), R.r + cobW + 8, y + .5); }
  /* legenda jasności */
  { const lx = R.l + 8, ly = R.t + 8, gw = 96; ctx.fillStyle = 'rgba(3,4,8,.8)'; ctx.fillRect(lx - 4, ly - 4, gw + 176, 30); const g = ctx.createLinearGradient(lx, 0, lx + gw, 0);
    for (let i = 0; i <= 10; i++) g.addColorStop(i / 10, rgb(lut, i / 10)); ctx.fillStyle = g; ctx.fillRect(lx, ly + 14, gw, 6);
    ctx.font = F9; ctx.fillStyle = 'rgba(201,203,209,1)'; ctx.textAlign = 'left'; ctx.fillText('PŁYNNOŚĆ OCZEKUJĄCA · wiersz ' + fx.fmtP(H.row), lx, ly + 4);
    ctx.fillStyle = 'rgba(137,139,145,1)'; ctx.fillText('0', lx - 0, ly + 28 - 1); ctx.fillText('≥ ' + (H.ref != null ? (H.ref >= 10 ? Math.round(H.ref) : H.ref.toFixed(2)) : '—') + ' (97. percentyl okna)', lx + gw + 8, ly + 17); }
  if (o.bub && !H.bubbles.length) { ctx.font = F9; ctx.textAlign = 'right'; ctx.fillStyle = 'rgba(3,4,8,.8)'; const t = H.src === 'MT5' ? 'BĄBLE TRANSAKCJI: brak taśmy transakcji u brokera (OTC) – nie są szacowane' : 'BĄBLE TRANSAKCJI: brak transakcji w oknie';
    const w = ctx.measureText(t).width + 12; ctx.fillRect(R.r - w - 6, R.t + 4, w, 16); ctx.fillStyle = 'rgba(217,201,154,1)'; ctx.fillText(t, R.r - 12, R.t + 12); }
  /* celownik */
  let hover = null; const hv = o.hover;
  if (hv && hv.x > R.l && hv.x < R.r && hv.y > R.t && hv.y < priceB) {
    const t = tStart + (hv.x - R.l) / (R.r - R.l) * (tEnd - tStart), p = st.yMax - (hv.y - R.t) / (priceB - R.t) * (st.yMax - st.yMin), r = rowOf(p, H.row);
    const c = t > tNow ? null : H.cols.find((x) => t >= x.t && t < x.t1); const cell = c && c.cells.find((x) => Math.abs(x[0] - r) < H.row / 2);
    const lv = t > tNow && d ? [...d.bids, ...d.asks].find(([pp]) => Math.abs(rowOf(pp, H.row) - r) < H.row / 2) : null;
    hover = { t: Math.min(t, tNow), p, row: r, q: cell ? cell[1] : lv ? lv[1] : null, bid: c ? c.bid : bb, ask: c ? c.ask : ba, n: c ? c.n : null, cob: t > tNow };
    const x = Math.round(hv.x) + .5, y = Math.round(hv.y) + .5; ctx.strokeStyle = 'rgba(236,239,245,.45)'; ctx.beginPath(); ctx.moveTo(x, R.t); ctx.lineTo(x, R.b); ctx.moveTo(R.l, y); ctx.lineTo(R.r, y); ctx.stroke();
    ctx.fillStyle = '#11151d'; ctx.fillRect(R.r + cobW + 1, y - 11, axW - 2, 22); ctx.fillStyle = '#dfe3eb'; ctx.textAlign = 'left'; ctx.fillText(fx.fmtP(p), R.r + cobW + 8, y);
    const tl = hover.cob ? 'ARKUSZ TERAZ' : fT(hover.t, true), tw = ctx.measureText(tl).width + 18; ctx.fillStyle = '#11151d'; ctx.fillRect(x - tw / 2, R.b + 1, tw, 20); ctx.fillStyle = '#dfe3eb'; ctx.textAlign = 'center'; ctx.fillText(tl, x, R.b + 11);
  }
  ctx.globalAlpha = 1; ctx.restore();
  return { R, priceB, hover, bubbles: bubbleN, fT, bid: bb, ask: ba };
}
