// Porównanie portu PMW-SVP-1 (frontend) z silnikiem bota. Uruchom: node update_charts/narzedzia/svp_zgodnosc/test_svp_port.mjs <ścieżka do portu.js>
import fs from 'node:fs'; import path from 'node:path'; import { createRequire } from 'node:module'; import { fileURLToPath } from 'node:url';
const here = path.dirname(fileURLToPath(import.meta.url)); const require = createRequire(import.meta.url);
const port = require(path.resolve(process.argv[2] || path.join(here, '../../referencje/kod/svp_port_pmw_svp_1.js')));
const F = JSON.parse(fs.readFileSync(path.join(here, 'fixture_svp.json'))); const TF = { M1: 60, M5: 300, M15: 900 };
let ok = 0, bad = 0; const eq = (a, b) => Math.abs(a - b) < 1e-6; const eqA = (a, b) => a.length === b.length && a.every((x, i) => eq(x, b[i]));
for (const c of F.cases) {
  const r = port.svpCompute(F.bars[c.tf], TF[c.tf], c.start, c.end, F.as_of, { tick: .01, binTicks: c.bin_ticks, va: .70 }); const e = c.expect;
  const same = r.status === e.status && (e.status === 'NO_DATA' || (eq(r.poc, e.poc) && eq(r.vah, e.vah) && eq(r.val, e.val) && eqA(r.hvn, e.hvn) && eqA(r.lvn, e.lvn) && r.bars === e.bars));
  if (same) ok++; else { bad++; console.log('RÓŻNICA', c.tf, c.session, c.local_date, { port: [r.poc, r.vah, r.val, r.bars], bot: [e.poc, e.vah, e.val, e.bars] }); }
}
console.log(`zgodne: ${ok}, różne: ${bad}`); process.exit(bad ? 1 : 0);
