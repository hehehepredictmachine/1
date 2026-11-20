// Panele systemowe 1.42 (E7, S6): Ustawienia (w tym MT5) · Tryb pracy · STOP · Diagnostyka w szufladzie nad bieżącym ekranem.
// Logika 1:1 z 1.41.0 – osadzone są TE SAME komponenty (SettingsModal, ModeDialog, PowerDialog z components/Dialogs.tsx): te same
// wywołania API, potwierdzenia i teksty. Nowy jest wyłącznie wygląd. Otwarcie panelu wysyła tylko GET.
import { lazy, Suspense, useEffect, useRef } from "react";
import { EmbedCtx, ModeDialog, PowerDialog, SettingsModal } from "../../components/Dialogs";
import DiagnosticsPanel from "./DiagnosticsPanel";
import { useLicense } from "../../license/LicenseGate";
import LicensePanel from "./LicensePanel";
// 1.44.0: generator licencji tylko w buildzie właściciela – w buildzie klienta (PMW_EDITION=CLIENT) ten import znika przy kompilacji
const LicenseGeneratorPanel = __PMW_EDITION__ === "OWNER" ? lazy(() => import("./LicenseGeneratorPanel")) : null;
import TrainingCenterPanel from "./TrainingCenterPanel";
import "./system.css";

export type SysPanel = "settings" | "mode" | "stop" | "diagnostics" | "training" | "license";
const TABS: [SysPanel, string][] = [["settings", "USTAWIENIA"], ["mode", "TRYB PRACY"], ["stop", "STOP"], ["diagnostics", "DIAGNOSTYKA"],
  ["training", "CENTRUM TRENINGOWE PEPE"], ["license", "LICENCJA"]];

export default function SystemDrawer({ panel, onPanel, onClose }: { panel: SysPanel; onPanel(p: SysPanel): void; onClose(): void }) {
  const ref = useRef<HTMLDivElement>(null);
  const lic = useLicense();
  const ownerTools = __PMW_EDITION__ === "OWNER" && LicenseGeneratorPanel !== null && lic.st?.edition !== "CLIENT";
  const label = (k: SysPanel, l: string) => (k === "license" && __PMW_EDITION__ === "OWNER" && ownerTools ? "GENERATOR LICENCJI" : l);
  const back = useRef<Element | null>(null);
  useEffect(() => {
    back.current = document.activeElement;
    ref.current?.querySelector<HTMLElement>(".sys-tabs button[aria-selected='true']")?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); onClose(); }
      if (e.key === "Tab" && ref.current) {                              // pułapka fokusu w szufladzie
        const f = [...ref.current.querySelectorAll<HTMLElement>("button,select,input,textarea,a[href]")].filter((x) => !x.hasAttribute("disabled"));
        if (!f.length) return;
        if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    };
    window.addEventListener("keydown", key, true);
    return () => { window.removeEventListener("keydown", key, true); (back.current as HTMLElement | null)?.focus?.(); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const idx = TABS.findIndex((t) => t[0] === panel);
  return (
    <div className="sys-layer" data-testid="system-drawer">
      <div className="sys-dim" onMouseDown={onClose} />
      <aside className={"sys-drawer cs-win" + (panel === "training" || panel === "license" ? " wide" : "")} role="dialog" aria-modal="true" aria-label={"Panel systemowy – " + label(TABS[idx][0], TABS[idx][1])} ref={ref} data-testid={"system-" + panel}>
        <i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" />
        <header className="sys-head"><span className="sys-num">SYS · {String(idx + 1).padStart(2, "0")}</span><b>{label(TABS[idx][0], TABS[idx][1])}</b>
          <button type="button" className="sys-x" aria-label="Zamknij panel" onClick={onClose}>✕</button></header>
        <nav className="sys-tabs" role="tablist">{TABS.map(([k, l]) => (
          <button key={k} type="button" role="tab" aria-selected={k === panel} className={k === "stop" ? "danger" : ""} onClick={() => onPanel(k)}>{label(k, l)}</button>))}</nav>
        <div className="sys-body" key={panel}>
          <EmbedCtx.Provider value={true}>
            {panel === "settings" && <SettingsModal onClose={onClose} />}
            {panel === "mode" && <ModeDialog onClose={onClose} />}
            {panel === "stop" && <PowerDialog onClose={onClose} />}
          </EmbedCtx.Provider>
          {panel === "diagnostics" && <DiagnosticsPanel />}
          {panel === "training" && <TrainingCenterPanel />}
          {panel === "license" && (__PMW_EDITION__ === "OWNER" && ownerTools && LicenseGeneratorPanel
            ? <Suspense fallback={<p className="sys-note">Wczytywanie…</p>}><LicenseGeneratorPanel /></Suspense> : <LicensePanel />)}
        </div>
      </aside>
    </div>);
}
