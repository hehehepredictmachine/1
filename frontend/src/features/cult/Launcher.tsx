// Launcher "JOIN THE CULT" (launcher.jpg). In the Windows app the launcher is the separate small start window (desktop/splash.html):
// the panel is loaded only after JOIN THE CULT. In a browser it is this small framed window, shown at the start of a session: the
// full panel is NOT mounted before the click. Flow: short launcher animation -> JOIN THE CULT -> full intro -> Main Menu.
import { useEffect, useState } from "react";
import { navigate } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { A } from "./assets";
import { Icon } from "./kit";
import "./cult.css";

const KEY = "mq.cult.joined";

/** The launcher gate: shown when a session starts on the bare address (no screen in the URL). A direct link to a screen, the Windows
 *  app (it opens the panel with ?pmw_joined=1 after its own launcher) and an earlier JOIN in this session skip it. */
export function launcherNeeded(): boolean {
  try {
    const q = new URLSearchParams(location.search);
    const h = (location.hash || "").replace(/^#\/?/, "");
    if (q.get("pmw_joined") === "1" || h) {
      sessionStorage.setItem(KEY, "1");
      return false;
    }
    return sessionStorage.getItem(KEY) !== "1";
  } catch {
    return false;                                         // storage blocked: never lock the user out of the panel
  }
}

export function markJoined() {
  try { sessionStorage.setItem(KEY, "1"); } catch { /* storage unavailable */ }
}

export default function Launcher({ onJoin }: { onJoin: () => void }) {
  const { s } = useStore();
  const [shown, setShown] = useState(false);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setShown(true), 30);
    return () => clearTimeout(t);
  }, []);
  const ready = !!s.loaded && s.ws === "OPEN";
  const join = () => {
    if (!ready || leaving) return;
    setLeaving(true);
    markJoined();
    setTimeout(() => { navigate("menu", { params: { intro: "1" } }); onJoin(); }, 450);
  };
  return (
    <div className={cls("cl-back", shown && "in", leaving && "out")} data-testid="cult-launcher">
      <div className="cl-swirl" aria-hidden="true" />
      <div className="cl-win" role="dialog" aria-label="PepeMarketWizard – launcher">
        <img className="cl-crown" src={A.crown} alt="" />
        <header className="cl-head">
          <span className="cl-ver" data-testid="cult-launcher-ver">v{s.app_version ?? "—"} LAUNCHER</span>
          <div className="cl-brand"><b>PEPEMARKETWIZARD</b><small>AI TRADING INTELLIGENCE</small></div>
        </header>
        <div className="cl-scene">
          <img src={A.launcher} alt="Pepe przemawia do zgromadzenia" draggable={false} />
          <i className="cl-halo" aria-hidden="true" />
          <i className="cl-beams" aria-hidden="true" />
          <span className="cl-sparks" aria-hidden="true">{Array.from({ length: 18 }, (_, i) => <i key={i} style={{ "--i": i } as React.CSSProperties} />)}</span>
        </div>
        <h1 className="cl-title">JOIN THE CULT</h1>
        <p className="cl-orn" aria-hidden="true"><i />◆<i /></p>
        <ul className="cl-feat">
          <li><Icon n="bolt" />AI SIGNALS</li><li><Icon n="bars" />QUANT ANALYTICS</li><li><Icon n="flask" />STRATEGY LAB</li><li><Icon n="grid" />AUTO TRADING</li>
        </ul>
        <button type="button" className="cl-join" onClick={join} disabled={!ready} data-testid="cult-join" autoFocus>
          <span className="cl-p">P</span>JOIN THE CULT<span className="cl-arr">»</span></button>
        <p className={cls("cl-status", ready ? "ok" : "wait")} role="status" data-testid="cult-status">
          <i />{ready ? "SYSTEM READY" : s.loaded ? `ŁĄCZENIE Z SILNIKIEM… (${s.ws ?? "?"})` : "ŁĄCZENIE Z SILNIKIEM…"}</p>
      </div>
    </div>);
}
