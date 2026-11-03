// Per-chart settings dialog and layer menu (1.29). Changes apply live to this one chart and are saved locally under its key
// (chart id + symbol + TF); "Przywróć domyślne" drops the saved set; templates copy a set between charts. Presentation only.
import { useEffect, useRef, useState } from "react";
import {
  DEFAULT_PREFS, deleteTemplate, LAYERS, listTemplates, saveTemplate, type ChartPrefs, type LayerId,
} from "../chartprefs";

const COLORS: [keyof ChartPrefs, string][] = [
  ["upColor", "Świeca wzrostowa"], ["downColor", "Świeca spadkowa"], ["wickUp", "Knot wzrostowy"], ["wickDown", "Knot spadkowy"],
  ["background", "Tło"], ["gridColor", "Siatka"], ["textColor", "Tekst / osie"],
];

export function ChartSettingsDialog({ title, prefs, onChange, onReset, onClose, fallback }: {
  title: string; prefs: ChartPrefs; onChange: (p: ChartPrefs) => void; onReset: () => void; onClose: () => void;
  fallback: Record<string, string>;                  // colours of the active theme (shown when the chart has no own colour)
}) {
  const [tpls, setTpls] = useState(listTemplates);
  const [tplName, setTplName] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("button, select, input")?.focus();
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  const set = (patch: Partial<ChartPrefs>) => onChange({ ...prefs, ...patch });
  const setZone = (id: LayerId, k: "up" | "down" | "opacity", v: string | number) =>
    set({ zones: { ...prefs.zones, [id]: { ...prefs.zones[id], [k]: v } } });
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide chart-settings" role="dialog" aria-modal="true" aria-label={`Ustawienia wykresu ${title}`} ref={ref} data-testid="chart-settings">
        <div className="modal-head"><b>Ustawienia wykresu – {title}</b><span className="spacer" />
          <button className="icon" onClick={onClose} aria-label="Zamknij" data-testid="cs-close">✕</button></div>
        <div className="modal-body">
          <p className="small muted">Dotyczy tylko tego wykresu (instrument + interwał). Zapis lokalny – przywracany po ponownym uruchomieniu.</p>
          <fieldset className="cs-group"><legend>Kolory</legend>
            <div className="cs-colors">
              {COLORS.map(([k, label]) => {
                const own = prefs[k] as string | null;
                return (
                  <label key={k} className="cs-color">
                    <input type="color" value={own ?? toHex6(fallback[k] ?? "#888888")} data-testid={`cs-${k}`}
                      onChange={(e) => set({ [k]: e.target.value } as Partial<ChartPrefs>)} />
                    <span>{label}</span>
                    {own ? <button className="link small" onClick={() => set({ [k]: null } as Partial<ChartPrefs>)} title="Kolor motywu">motyw</button>
                      : <em className="small muted">motyw</em>}
                  </label>);
              })}
            </div>
          </fieldset>
          <fieldset className="cs-group"><legend>Widok</legend>
            <div className="row">
              <label className="field"><span>Rozmiar tekstu</span>
                <input type="range" min={9} max={16} value={prefs.fontSize} data-testid="cs-font" onChange={(e) => set({ fontSize: Number(e.target.value) })} />
                <b>{prefs.fontSize} px</b></label>
              <label className="field"><span>Strefa czasu</span>
                <select value={prefs.tz} data-testid="cs-tz" onChange={(e) => set({ tz: e.target.value as ChartPrefs["tz"] })}>
                  <option value="PAGE">jak na stronie</option><option value="LOCAL">lokalna</option><option value="UTC">UTC</option><option value="SERVER">serwera MT5</option>
                </select></label>
              <label className="cs-check"><input type="checkbox" checked={prefs.showGrid} data-testid="cs-grid" onChange={(e) => set({ showGrid: e.target.checked })} /> siatka</label>
              <label className="cs-check"><input type="checkbox" checked={prefs.showVolume} data-testid="cs-volume" onChange={(e) => set({ showVolume: e.target.checked })} /> wolumen (tick)</label>
              <label className="cs-check"><input type="checkbox" checked={prefs.marketZones} data-testid="cs-mz" onChange={(e) => set({ marketZones: e.target.checked })} /> strefy rynkowe</label>
              <label className="cs-check"><input type="checkbox" checked={prefs.labels} data-testid="cs-labels" onChange={(e) => set({ labels: e.target.checked })} /> etykiety stref</label>
            </div>
            <p className="small muted">Przybliżenie, przesunięcie i automatyczna skala ceny są zapamiętywane osobno dla tego wykresu (przyciski +, −, Dopasuj, A).</p>
          </fieldset>
          <fieldset className="cs-group"><legend>Warstwy stref – kolor i krycie</legend>
            <table className="cs-zones"><thead><tr><th>Warstwa</th><th>Widoczna</th><th>▲ / wsparcie</th><th>▼ / opór</th><th>Krycie</th></tr></thead>
              <tbody>{LAYERS.map(([id, label, hint]) => (
                <tr key={id} title={hint}>
                  <td>{label}</td>
                  <td><input type="checkbox" checked={prefs.layers[id]} data-testid={`cs-layer-${id}`}
                    onChange={(e) => set({ layers: { ...prefs.layers, [id]: e.target.checked } })} /></td>
                  <td><input type="color" value={prefs.zones[id].up} onChange={(e) => setZone(id, "up", e.target.value)} aria-label={`${label} kolor wzrostowy`} /></td>
                  <td><input type="color" value={prefs.zones[id].down} onChange={(e) => setZone(id, "down", e.target.value)} aria-label={`${label} kolor spadkowy`} /></td>
                  <td><input type="range" min={2} max={60} value={Math.round(prefs.zones[id].opacity * 100)} data-testid={`cs-opacity-${id}`}
                    onChange={(e) => setZone(id, "opacity", Number(e.target.value) / 100)} aria-label={`${label} krycie`} /> {Math.round(prefs.zones[id].opacity * 100)}%</td>
                </tr>))}</tbody></table>
          </fieldset>
          <fieldset className="cs-group"><legend>Szablony</legend>
            <div className="row">
              <input placeholder="nazwa szablonu" value={tplName} maxLength={40} onChange={(e) => setTplName(e.target.value)} data-testid="cs-tpl-name" />
              <button className="btn tiny" disabled={!tplName.trim()} data-testid="cs-tpl-save"
                onClick={() => { saveTemplate(tplName, prefs); setTpls(listTemplates()); setTplName(""); }}>Zapisz jako szablon</button>
              <select value="" data-testid="cs-tpl-apply" onChange={(e) => { const t = tpls[e.target.value]; if (t) onChange(t); }}>
                <option value="">— zastosuj szablon —</option>
                {Object.keys(tpls).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <select value="" onChange={(e) => { if (e.target.value) { deleteTemplate(e.target.value); setTpls(listTemplates()); } }} aria-label="Usuń szablon">
                <option value="">— usuń szablon —</option>
                {Object.keys(tpls).map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
            </div>
          </fieldset>
          <div className="row">
            <button className="btn" data-testid="cs-reset" onClick={onReset}>Przywróć domyślne</button>
            <span className="spacer" />
            <button className="btn primary" onClick={onClose}>Gotowe</button>
          </div>
        </div>
      </div>
    </div>);
}

/** Quick layer menu of a chart toolbar: FVG / OB / S&D / S/R / liquidity / labels. */
export function LayerMenu({ prefs, onChange, testid }: { prefs: ChartPrefs; onChange: (p: ChartPrefs) => void; testid?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", h);
    window.addEventListener("keydown", k);
    return () => { document.removeEventListener("mousedown", h); window.removeEventListener("keydown", k); };
  }, [open]);
  const hidden = LAYERS.filter(([id]) => !prefs.layers[id]).length + (prefs.labels ? 0 : 1);
  return (
    <div className="layer-menu" ref={ref}>
      <button className={"icon" + (hidden ? " on" : "")} aria-haspopup="true" aria-expanded={open} data-testid={testid ?? "layers-btn"}
        title="Warstwy stref na tym wykresie" onClick={() => setOpen(!open)}>Warstwy{hidden ? ` (−${hidden})` : ""}</button>
      {open && (
        <div className="layer-pop" role="menu" aria-label="Warstwy stref">
          {LAYERS.map(([id, label, hint]) => (
            <label key={id} role="menuitemcheckbox" aria-checked={prefs.layers[id]} title={hint}>
              <input type="checkbox" checked={prefs.layers[id]} data-layer={id}
                onChange={(e) => onChange({ ...prefs, layers: { ...prefs.layers, [id]: e.target.checked } })} />
              <i className="sw" style={{ background: prefs.zones[id].up }} /><i className="sw" style={{ background: prefs.zones[id].down }} /> {label}
            </label>))}
          <label role="menuitemcheckbox" aria-checked={prefs.labels}>
            <input type="checkbox" checked={prefs.labels} data-layer="LABELS" onChange={(e) => onChange({ ...prefs, labels: e.target.checked })} /> Etykiety
          </label>
          <button className="link small" onClick={() => onChange({ ...prefs, layers: { ...DEFAULT_PREFS.layers }, labels: true })}>pokaż wszystkie</button>
        </div>)}
    </div>);
}

function toHex6(c: string): string {
  if (/^#[0-9a-f]{6}/i.test(c)) return c.slice(0, 7);
  const m = /rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)/.exec(c);
  if (m) return "#" + [m[1], m[2], m[3]].map((x) => Number(x).toString(16).padStart(2, "0")).join("");
  return "#888888";
}
