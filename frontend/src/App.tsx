// Apollo23 (dawniej PepeMarketWizard) – trasy: #/menu (film intro + menu FOREX / CRYPTO / TraderLifeGame), #/trader-life-game (gra, 1.45), #/forex (kula FOREX i 4 ekrany
// planet) oraz #/system?p=… (panele systemowe w szufladzie nad ekranem, z którego je otwarto). Stary interfejs 1.41 jest w archive/ui_1_41.
// Store (jeden WebSocket) jest nad tym komponentem (main.tsx), więc przejścia między trasami nie zrywają połączenia.
import { useEffect, useState, type CSSProperties } from "react";
import CinematicMenu from "./features/cinematic/CinematicMenu";
import ForexScene, { POSE_KEY } from "./features/forex/ForexScene";
import TraderLifeGame from "./features/trader-life-game/TraderLifeGame";
import { BRAND } from "./brand";
import { ExecStatus, SystemIcons } from "./features/system/SystemBar";
import SystemDrawer, { type SysPanel } from "./features/system/SystemDrawer";
import { FOREX_SCREENS, navigate, parse, SYSTEM_PANELS, useRoute, type ForexScreen } from "./router";
import { requireLicense, useLicense } from "./license/LicenseGate";
import { useStore } from "./store";

// 1.46: notka nad menu kinowym (menu jest position:fixed na cały ekran); style inline, bo system.css stylizuje .sys-note / .act tylko w szufladzie
const OTC_NOTE: CSSProperties = { position: "fixed", top: 12, left: "50%", transform: "translateX(-50%)", zIndex: 45, margin: 0, maxWidth: "calc(100vw - 32px)",
  background: "rgba(6,8,13,.95)", border: "1px solid #2b303b", color: "#c4c8d1" };
const OTC_OK: CSSProperties = { marginLeft: 10, background: "transparent", border: "1px solid #3a4152", color: "#dfe3eb", font: "inherit", padding: "2px 10px", cursor: "pointer" };

export default function App() {
  const { s } = useStore();
  const lic = useLicense().st;
  const route = useRoute();
  const [firstRunPending, setFirstRunPending] = useState(false);
  // 1.46: #/otc i #/otc-gold -> #/menu?retired=otc (kontrakt 1.45 TASK 020) – parametru nikt nie czytał, użytkownik ze starą zakładką trafiał do menu
  // bez informacji; teraz notka z tekstem backendu (_OTC_RETIRED), OK chowa ją do końca sesji panelu (adres zostaje bez zmian)
  const [otcNoteClosed, setOtcNoteClosed] = useState(false);
  // panel systemowy: #/system?p=…&from=<hash ekranu źródłowego>; pod szufladą zostaje ekran źródłowy (bez remontu)
  const from = route.page === "system" ? decodeURIComponent(route.params.get("from") || "#/menu") : null;
  const base = route.page === "system" ? parse(from || "#/menu") : route;
  const panel = route.page === "system" ? ((SYSTEM_PANELS as readonly string[]).includes(route.params.get("p") || "") ? route.params.get("p") as SysPanel : "settings") : null;
  const openSystem = (p: SysPanel) => navigate("system", { params: { p, from: route.page === "system" ? from : location.hash } });
  const otcRetired = base.page === "menu" && base.params.get("retired") === "otc" && !otcNoteClosed;
  const closeSystem = () => { if (from) { history.replaceState(null, "", from); window.dispatchEvent(new HashChangeEvent("hashchange")); } else navigate("menu"); };

  useEffect(() => {
    // S5 F4: pierwsze uruchomienie – Ustawienia po intro (na trasie menu po wejściu do menu)
    if (s.loaded && s.first_run_completed === false) { if (base.page === "menu") setFirstRunPending(true); else openSystem("settings"); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.loaded]);
  useEffect(() => { document.title = base.page === "forex" ? `${BRAND} – FOREX` : base.page === "trader-life-game" ? `${BRAND} – TraderLifeGame` : BRAND; }, [base.page]);

  if (!s.loaded) return <div className="pmw-loading" role="status">{BRAND.toUpperCase()} · łączenie z lokalnym backendem…</div>;
  const screen = base.page === "forex" ? ((FOREX_SCREENS as readonly string[]).includes(base.params.get("s") || "") ? base.params.get("s") as ForexScreen : null) : null;
  return (<>
    {base.page === "trader-life-game"
      ? <TraderLifeGame key="tlg" onBack={() => navigate("menu")} />
      : base.page === "forex"
      ? <ForexScene key="forex" screen={screen} fromMenu={base.params.get("from") === "menu"} onSystem={openSystem} />
      // 1.46: bez nieużywanego onSettings – ustawienia otwiera pasek ikon systemowych (SystemIcons)
      : <><CinematicMenu key="menu"
          onMenuReady={() => { if (firstRunPending) { setFirstRunPending(false); openSystem("settings"); } }}
          onForexReady={(pose, signal) => { try { sessionStorage.setItem(POSE_KEY, JSON.stringify(pose)); } catch { /* */ }
            // 1.44.0: centralna kontrola licencji przed uruchomieniem trybu (402 -> ekran aktywacji)
            // 1.46: przekazanie anulowane w trakcie sprawdzania licencji (POWRÓT / Esc / intro / błąd renderera / odmontowanie) – bez przejścia do #/forex
            void requireLicense("FOREX").then((ok) => { if (ok && !signal.aborted) navigate("forex", { params: { from: "menu" }, replace: true }); }); }}
          onGameReady={() => navigate("trader-life-game")} />
        <ExecStatus onOpen={openSystem} /><SystemIcons onOpen={openSystem} />
        {otcRetired && <p className="sys-note" role="status" data-testid="otc-retired-note" style={OTC_NOTE}>
          Strategie OTC zostały wycofane ({BRAND}, TASK 020). Historia zostaje tylko do odczytu.
          <button type="button" className="act" style={OTC_OK} data-testid="otc-retired-ok" onClick={() => setOtcNoteClosed(true)}>OK</button></p>}</>}
    {lic?.warn && <button type="button" className={"lic-warnchip" + (base.page === "forex" ? " forex" : "")} data-testid="license-warnchip" onClick={() => openSystem("license")}>
      LICENCJA WYGASA ZA {lic.days_left} {lic.days_left === 1 ? "DZIEŃ" : "DNI"} · {lic.exp_local} · ZMIEŃ KLUCZ</button>}
    {panel && <SystemDrawer panel={panel} onPanel={(p) => navigate("system", { params: { p, from }, replace: true })} onClose={closeSystem} />}
  </>);
}
