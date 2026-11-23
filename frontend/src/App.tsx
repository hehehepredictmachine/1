// Apollo23 (dawniej PepeMarketWizard) – trasy: #/menu (film intro + menu FOREX / CRYPTO / TraderLifeGame), #/trader-life-game (gra, 1.45), #/forex (kula FOREX i 4 ekrany
// planet) oraz #/system?p=… (panele systemowe w szufladzie nad ekranem, z którego je otwarto). Stary interfejs 1.41 jest w archive/ui_1_41.
// Store (jeden WebSocket) jest nad tym komponentem (main.tsx), więc przejścia między trasami nie zrywają połączenia.
import { useEffect, useState } from "react";
import CinematicMenu from "./features/cinematic/CinematicMenu";
import ForexScene, { POSE_KEY } from "./features/forex/ForexScene";
import TraderLifeGame from "./features/trader-life-game/TraderLifeGame";
import { BRAND } from "./brand";
import { ExecStatus, SystemIcons } from "./features/system/SystemBar";
import SystemDrawer, { type SysPanel } from "./features/system/SystemDrawer";
import { FOREX_SCREENS, navigate, parse, SYSTEM_PANELS, useRoute, type ForexScreen } from "./router";
import { requireLicense, useLicense } from "./license/LicenseGate";
import { useStore } from "./store";

export default function App() {
  const { s } = useStore();
  const lic = useLicense().st;
  const route = useRoute();
  const [firstRunPending, setFirstRunPending] = useState(false);
  // panel systemowy: #/system?p=…&from=<hash ekranu źródłowego>; pod szufladą zostaje ekran źródłowy (bez remontu)
  const from = route.page === "system" ? decodeURIComponent(route.params.get("from") || "#/menu") : null;
  const base = route.page === "system" ? parse(from || "#/menu") : route;
  const panel = route.page === "system" ? ((SYSTEM_PANELS as readonly string[]).includes(route.params.get("p") || "") ? route.params.get("p") as SysPanel : "settings") : null;
  const openSystem = (p: SysPanel) => navigate("system", { params: { p, from: route.page === "system" ? from : location.hash } });
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
      : <><CinematicMenu key="menu" onSettings={() => openSystem("settings")}
          onMenuReady={() => { if (firstRunPending) { setFirstRunPending(false); openSystem("settings"); } }}
          onForexReady={(pose) => { try { sessionStorage.setItem(POSE_KEY, JSON.stringify(pose)); } catch { /* */ }
            // 1.44.0: centralna kontrola licencji przed uruchomieniem trybu (402 -> ekran aktywacji)
            void requireLicense("FOREX").then((ok) => { if (ok) navigate("forex", { params: { from: "menu" }, replace: true }); }); }}
          onGameReady={() => navigate("trader-life-game")} />
        <ExecStatus onOpen={openSystem} /><SystemIcons onOpen={openSystem} /></>}
    {lic?.warn && <button type="button" className={"lic-warnchip" + (base.page === "forex" ? " forex" : "")} data-testid="license-warnchip" onClick={() => openSystem("license")}>
      LICENCJA WYGASA ZA {lic.days_left} {lic.days_left === 1 ? "DZIEŃ" : "DNI"} · {lic.exp_local} · ZMIEŃ KLUCZ</button>}
    {panel && <SystemDrawer panel={panel} onPanel={(p) => navigate("system", { params: { p, from }, replace: true })} onClose={closeSystem} />}
  </>);
}
