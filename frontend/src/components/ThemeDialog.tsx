import { useEffect, useMemo, useRef, useState } from "react";
import {
  CHART_GROUPS, contrastWarnings, exportTheme, GROUPS, hslToRgb, hsvToRgb, parseColor, parseThemeFile, PRESETS, rgbToHsl, rgbToHsv,
  toHex, TOKENS, useTheme, type RGBA, type Tokens,
} from "../theme";
import { cls } from "../util";

// ------------------------------------------------------------------ colour picker (HSV square + hue + alpha + HEX/RGB/HSL)
export function ColorPicker({ value, onChange }: { value: string; onChange: (hex: string) => void }) {
  const c = parseColor(value) ?? { r: 0, g: 0, b: 0, a: 1 };
  const [hsv, setHsv] = useState(() => rgbToHsv(c));
  const lastEmitted = useRef(value);
  // follow external changes (other token selected / preset) without fighting the user's drag
  useEffect(() => {
    if (value !== lastEmitted.current) {
      const n = parseColor(value);
      if (n) setHsv(rgbToHsv(n));
      lastEmitted.current = value;
    }
  }, [value]);
  const emit = (rgba: RGBA) => {
    const hex = toHex(rgba);
    lastEmitted.current = hex;
    onChange(hex);
  };
  const fromHsv = (h: number, s: number, v: number, a = c.a) => {
    setHsv({ h, s, v });
    emit({ ...hsvToRgb(h, s, v), a });
  };
  const sq = useRef<HTMLDivElement>(null);
  const drag = (e: React.PointerEvent) => {
    const r = sq.current!.getBoundingClientRect();
    const s = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    const v = 1 - Math.min(1, Math.max(0, (e.clientY - r.top) / r.height));
    fromHsv(hsv.h, s, v);
  };
  const hsl = rgbToHsl(c);
  const [hexText, setHexText] = useState(toHex(c));
  useEffect(() => setHexText(toHex(c)), [value]); // eslint-disable-line react-hooks/exhaustive-deps
  const num = (label: string, v: number, max: number, set: (x: number) => void, step = 1) => (
    <label className="cp-num"><span>{label}</span>
      <input type="number" min={0} max={max} step={step} value={Math.round(v * (step < 1 ? 100 : 1)) / (step < 1 ? 100 : 1)}
        onChange={(e) => { const x = Number(e.target.value); if (Number.isFinite(x) && x >= 0 && x <= max) set(x); }} />
    </label>
  );
  return (
    <div className="cpicker" data-testid="color-picker">
      <div ref={sq} className="cp-square" style={{ background: `hsl(${hsv.h} 100% 50%)` }}
        onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture(e.pointerId); drag(e); }}
        onPointerMove={(e) => e.buttons && drag(e)}>
        <div className="cp-white" /><div className="cp-black" />
        <i className="cp-dot" style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%` }} />
      </div>
      <input className="cp-hue" type="range" min={0} max={359} value={Math.round(hsv.h)} aria-label="Odcień"
        onChange={(e) => fromHsv(Number(e.target.value), hsv.s, hsv.v)} />
      <input className="cp-alpha" type="range" min={0} max={100} value={Math.round(c.a * 100)} aria-label="Przezroczystość (alfa)"
        style={{ ["--cp-solid" as any]: toHex({ ...c, a: 1 }) }} onChange={(e) => emit({ ...c, a: Number(e.target.value) / 100 })} />
      <div className="cp-row">
        <label className="cp-num wide"><span>HEX</span>
          <input value={hexText} onChange={(e) => { setHexText(e.target.value); const n = parseColor(e.target.value); if (n) { setHsv(rgbToHsv(n)); emit(n); } }} />
        </label>
        <span className="cp-swatch" style={{ ["--sw" as any]: value }} title={value} />
      </div>
      <div className="cp-row">
        {num("R", c.r, 255, (x) => { const n = { ...c, r: x }; setHsv(rgbToHsv(n)); emit(n); })}
        {num("G", c.g, 255, (x) => { const n = { ...c, g: x }; setHsv(rgbToHsv(n)); emit(n); })}
        {num("B", c.b, 255, (x) => { const n = { ...c, b: x }; setHsv(rgbToHsv(n)); emit(n); })}
        {num("A", c.a, 1, (x) => emit({ ...c, a: x }), 0.01)}
      </div>
      <div className="cp-row">
        {num("H", hsl.h, 360, (x) => { const n = { ...hslToRgb(x, hsl.s, hsl.l), a: c.a }; setHsv(rgbToHsv(n)); emit(n); })}
        {num("S%", hsl.s * 100, 100, (x) => { const n = { ...hslToRgb(hsl.h, x / 100, hsl.l), a: c.a }; setHsv(rgbToHsv(n)); emit(n); })}
        {num("L%", hsl.l * 100, 100, (x) => { const n = { ...hslToRgb(hsl.h, hsl.s, x / 100), a: c.a }; setHsv(rgbToHsv(n)); emit(n); })}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ dialog "Wygląd"
export function ThemeDialog({ onClose }: { onClose: () => void }) {
  const th = useTheme();
  const { stored, draft } = th;
  useEffect(() => { th.beginEdit(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [scope, setScope] = useState<string>("global");
  const [sel, setSel] = useState<string>("accent");
  const [group, setGroup] = useState<string>(GROUPS[0]);
  const [msg, setMsg] = useState<string | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [name, setName] = useState("Mój motyw");
  const file = useRef<HTMLInputElement>(null);
  const d = draft;
  const merged = useMemo<Tokens>(() => (d ? (scope === "global" ? d.tokens : { ...d.tokens, ...(d.overrides[scope] || {}) }) : stored.tokens), [d, scope, stored]);
  const warn = useMemo(() => contrastWarnings(merged), [merged]);
  if (!d) return null;
  const visible = TOKENS.filter((t) => t.group === group && (scope === "global" || CHART_GROUPS.includes(t.group)));
  const setToken = (k: string, v: string | number) => {
    if (scope === "global") th.setDraft({ ...d, tokens: { ...d.tokens, [k]: v }, preset: "custom" });
    else th.setDraft({ ...d, overrides: { ...d.overrides, [scope]: { ...(d.overrides[scope] || {}), [k]: v } } });
  };
  const close = () => { th.cancel(); onClose(); };
  const doImport = async (f: File) => {
    const r = parseThemeFile(await f.text());
    setErrors(r.errors);
    if (r.errors.length) { setMsg("Import odrzucony – popraw plik (nic nie zostało zmienione)."); return; }
    th.setDraft({ tokens: { ...d.tokens, ...r.tokens }, overrides: r.overrides, preset: "custom" });
    setMsg(`Zaimportowano „${r.name}” jako podgląd – kliknij Zastosuj, aby zapisać.`);
  };
  const doExport = () => {
    const blob = new Blob([exportTheme(name, d.tokens, d.overrides)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `masterquo-motyw-${name.replace(/\s+/g, "_")}.json`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };
  const def = TOKENS.find((t) => t.key === sel);
  const overridden = scope !== "global" && d.overrides[scope]?.[sel] !== undefined;
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && close()}>
      <div className="modal wide theme-dialog" role="dialog" aria-label="Wygląd – kolory">
        <div className="modal-head"><b>Wygląd – pełna paleta kolorów</b><span className="spacer" /><button className="icon" onClick={close} title="Anuluj">✕</button></div>
        <div className="modal-body">
          <div className="row">
            <label className="field"><span>Motyw bazowy</span>
              <select value={d.preset in PRESETS ? d.preset : ""} onChange={(e) => th.setDraft({ ...d, tokens: { ...PRESETS[e.target.value].tokens }, preset: e.target.value })}>
                <option value="" disabled>własny</option>
                {Object.entries(PRESETS).map(([k, p]) => <option key={k} value={k}>{p.label}</option>)}
              </select></label>
            <label className="field"><span>Moje motywy</span>
              <select value="" onChange={(e) => e.target.value && th.setDraft({ ...d, tokens: { ...stored.custom[e.target.value] }, preset: "custom" })}>
                <option value="">— wczytaj —</option>
                {Object.keys(stored.custom).map((n) => <option key={n} value={n}>{n}</option>)}
              </select></label>
            <label className="field"><span>Zakres zmian</span>
              <select value={scope} onChange={(e) => { setScope(e.target.value); if (e.target.value !== "global" && !CHART_GROUPS.includes(group)) setGroup("Wykres"); }}>
                <option value="global">Cała aplikacja (globalnie)</option>
                {[1, 2, 3, 4, 5, 6].map((i) => <option key={i} value={`panel${i}`}>Tylko wykres {i}</option>)}
              </select></label>
          </div>
          <div className="theme-grid">
            <div className="theme-groups">
              {GROUPS.filter((g) => scope === "global" || CHART_GROUPS.includes(g)).map((g) =>
                <button key={g} className={cls("tbtn", group === g && "on")} onClick={() => setGroup(g)}>{g}</button>)}
            </div>
            <div className="theme-tokens">
              {visible.map((t) => (
                <button key={t.key} className={cls("tok", sel === t.key && "on")} onClick={() => setSel(t.key)}>
                  {t.kind === "color" ? <span className="cp-swatch" style={{ ["--sw" as any]: String(merged[t.key]) }} /> : <span className="tok-num">{Number(merged[t.key]).toFixed(2)}</span>}
                  <span>{t.label}</span>
                  {scope !== "global" && d.overrides[scope]?.[t.key] !== undefined && <i className="tag">własny</i>}
                </button>
              ))}
            </div>
            <div className="theme-edit">
              {def && <>
                <b>{def.label}</b>
                {def.kind === "color" ? <ColorPicker value={String(merged[def.key])} onChange={(v) => setToken(def.key, v)} /> :
                  <label className="field"><span>{def.min} – {def.max}</span>
                    <input type="range" min={def.min} max={def.max} step={def.step} value={Number(merged[def.key])} onChange={(e) => setToken(def.key, Number(e.target.value))} />
                    <b>{Number(merged[def.key]).toFixed(2)}</b></label>}
                {overridden && <button className="btn tiny ghost" onClick={() => {
                  const o = { ...(d.overrides[scope] || {}) };
                  delete o[sel];
                  th.setDraft({ ...d, overrides: { ...d.overrides, [scope]: o } });
                }}>Usuń nadpisanie dla tego wykresu</button>}
                {def.group === "Dekoracje (GIF)" && <small className="muted">Picker nie zmienia pikseli animacji GIF – reguluje tylko kolor i siłę przyciemnienia oraz przezroczystość warstw.
                  Dekoracje nie przechwytują kliknięć.</small>}
              </>}
            </div>
          </div>
          {warn.length > 0 && <div className="note warn"><b>Niski kontrast:</b><ul>{warn.map((w) => <li key={w}>{w}</li>)}</ul></div>}
          <small className="muted">Statusy są zawsze opisane także tekstem/ikoną (✓ ✗ ?), nie tylko kolorem. Zmiany widać od razu (podgląd); zapisują się po „Zastosuj”.</small>
          {msg && <div className="note">{msg}</div>}
          {errors.length > 0 && <div className="note bad"><b>Błędy pliku motywu:</b><ul>{errors.slice(0, 12).map((e) => <li key={e}>{e}</li>)}</ul></div>}
          <div className="row">
            <input value={name} onChange={(e) => setName(e.target.value.slice(0, 40))} aria-label="Nazwa motywu" />
            <button className="btn ghost" onClick={() => { th.saveCustom(name); setMsg(`Zapisano motyw „${name}”.`); }}>Zapisz jako mój motyw</button>
            {stored.custom[name] && <button className="btn ghost danger" onClick={() => th.deleteCustom(name)}>Usuń motyw</button>}
            <button className="btn ghost" onClick={doExport}>Eksport JSON</button>
            <button className="btn ghost" onClick={() => file.current?.click()}>Import JSON</button>
            <input ref={file} type="file" accept="application/json,.json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) doImport(f); e.target.value = ""; }} />
          </div>
          <div className="row end">
            <button className="btn ghost" onClick={() => th.resetDefaults()}>Przywróć domyślne</button>
            <button className="btn ghost" onClick={close}>Anuluj</button>
            <button className="btn" onClick={() => { th.apply(); onClose(); }}>Zastosuj</button>
          </div>
        </div>
      </div>
    </div>
  );
}
