// "Wygląd" dialog of the new panels: full colour choice (system colour picker + HEX), font size, animation intensity, presets and a
// live WCAG contrast check. Saved only in this client (browser / app window profile).
import { useEffect, useRef, useState } from "react";
import { cls } from "../../util";
import { contrast, DEFAULT_LOOK, lookStyle, PRESETS, validLook, type Look, type Motion } from "./look";

const COLORS: { k: "accent" | "bg" | "panel" | "text"; label: string }[] = [
  { k: "accent", label: "Akcent" },
  { k: "bg", label: "Tło" },
  { k: "panel", label: "Panel" },
  { k: "text", label: "Tekst" },
];
const MOTION: { v: Motion; label: string }[] = [
  { v: "full", label: "Pełne animacje" },
  { v: "reduced", label: "Ograniczone" },
  { v: "off", label: "Wyłączone" },
];

function Ratio({ label, a, b, min }: { label: string; a: string; b: string; min: number }) {
  const r = contrast(a, b);
  const ok = r >= min;
  return (
    <li className={ok ? "ok" : "bad"} data-contrast={ok ? "ok" : "low"}>
      <span>{label}</span><b>{r.toFixed(2)}:1</b><span>{ok ? `≥ ${min}:1 – czytelne` : `poniżej ${min}:1 – słaby kontrast`}</span>
    </li>);
}

export default function LookDialog({ look, onChange, onClose }: { look: Look; onChange: (l: Look) => void; onClose: () => void }) {
  const [draft, setDraft] = useState<Look>(look);
  const first = useRef<HTMLSelectElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    first.current?.focus();                             // once, when the dialog opens
    const k = (e: KeyboardEvent) => e.key === "Escape" && close.current();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  const set = (p: Partial<Look>) => {
    const n = { ...draft, ...p };
    setDraft(n);
    if (validLook(n)) onChange(n);                      // applied live; invalid HEX while typing is not applied
  };
  const st = lookStyle(draft) as any;
  return (
    <div className="t-modal-back" role="presentation" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="t-modal" role="dialog" aria-modal="true" aria-labelledby="t-look-title" data-testid="t-look">
        <header className="t-card-head"><h2 id="t-look-title">Wygląd</h2>
          <button className="t-btn" onClick={onClose} data-testid="t-look-close">Zamknij</button></header>
        <label className="t-field">Gotowy zestaw
          <select ref={first} value={PRESETS.find((p) => JSON.stringify(p.look) === JSON.stringify(draft))?.id ?? ""}
            onChange={(e) => { const p = PRESETS.find((x) => x.id === e.target.value); if (p) set(p.look); }} data-testid="t-look-preset">
            <option value="" disabled>własny</option>
            {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <div className="t-look-colors">
          {COLORS.map(({ k, label }) => (
            <label key={k} className="t-field t-color">{label}
              <span>
                <input type="color" value={draft[k]} onChange={(e) => set({ [k]: e.target.value } as Partial<Look>)} aria-label={`${label} – wybór koloru`}
                  data-testid={`t-look-${k}`} />
                <input type="text" value={draft[k]} maxLength={7} spellCheck={false} aria-label={`${label} – HEX`}
                  className={cls(!/^#[0-9a-f]{6}$/i.test(draft[k]) && "t-invalid")} onChange={(e) => set({ [k]: e.target.value.trim() } as Partial<Look>)} />
              </span>
            </label>))}
        </div>
        <label className="t-field">Wielkość czcionki: <b>{draft.fontSize}px</b>
          <input type="range" min={12} max={18} step={1} value={draft.fontSize} onChange={(e) => set({ fontSize: Number(e.target.value) })}
            data-testid="t-look-font" />
        </label>
        <fieldset className="t-field t-seg">
          <legend>Animacje</legend>
          {MOTION.map((m) => (
            <label key={m.v} className={cls(draft.motion === m.v && "on")}>
              <input type="radio" name="t-motion" value={m.v} checked={draft.motion === m.v} onChange={() => set({ motion: m.v })} />{m.label}
            </label>))}
        </fieldset>
        <p className="t-note">Ustawienie systemu „ogranicz ruch” zawsze wyłącza animacje, niezależnie od wyboru.</p>
        <div className="t-look-preview" style={st} aria-label="Podgląd">
          <span style={{ color: draft.text }}>Tekst panelu</span> <span style={{ color: st["--t-dim"] }}>tekst pomocniczy</span>{" "}
          <span className="t-look-acc" style={{ background: draft.accent, color: st["--t-accent-ink"] }}>akcent</span>
        </div>
        <ul className="t-contrast" aria-label="Kontrast (WCAG)" data-testid="t-look-contrast">
          <Ratio label="Tekst / panel" a={draft.text} b={draft.panel} min={4.5} />
          <Ratio label="Tekst / tło" a={draft.text} b={draft.bg} min={4.5} />
          <Ratio label="Tekst pomocniczy / panel" a={st["--t-dim"]} b={draft.panel} min={3} />
          <Ratio label="Akcent / tło" a={draft.accent} b={draft.bg} min={3} />
        </ul>
        <div className="t-row">
          <button className="t-btn" onClick={() => set(DEFAULT_LOOK)} data-testid="t-look-reset">Przywróć domyślne</button>
          <span className="t-note">Zapisywane tylko w tym kliencie (przeglądarka / okno aplikacji) – nie zmienia pracy bota.</span>
        </div>
      </div>
    </div>);
}
