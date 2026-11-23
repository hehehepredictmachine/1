// 1.46: pole liczbowe Ustawień – wpisywanie znak po znaku (kontrolowany <input>), przecinek i kropka dziesiętna.
import assert from "node:assert/strict";
import { parseNumText, syncNumText } from "../../frontend/src/components/numText.ts";

function typeInto(keys, start = null) {
  let value = start, text = start == null ? "" : String(start);
  for (const k of keys) {
    const typed = text + k;                    // the browser appends the key to what the field shows
    const n = parseNumText(typed);
    if (n !== undefined) value = n;            // committed only when complete
    text = syncNumText(typed, value);          // what React renders next
  }
  return { value, text };
}
assert.deepEqual(typeInto(["0", ".", "5"]), { value: 0.5, text: "0.5" });
assert.deepEqual(typeInto(["2", ",", "5"]), { value: 2.5, text: "2,5" });
assert.deepEqual(typeInto(["1", ".", "2", "5"]), { value: 1.25, text: "1.25" });
assert.equal(typeInto(["0", ".", "0", "5"]).value, 0.05);
assert.equal(parseNumText(""), null);
assert.equal(parseNumText("abc"), undefined);
assert.equal(parseNumText("-"), undefined);
assert.equal(parseNumText("1e309"), undefined);
assert.equal(syncNumText("", 3), "3");                                  // value loaded from the config is shown
// the 1.45.0 behaviour (Number(text) on every key) for the same keys gives 5, not 0.5:
let v = null; for (const k of ["0", ".", "5"]) { const t = (v == null ? "" : String(v)) + k; v = t === "" ? null : Number(t.replace(",", ".")); }
assert.equal(v, 5);
console.log("num_text OK");
