// Launcher "JOIN THE CULT". In the Windows app the launcher is the separate start window (desktop/splash.html): the panel is loaded only
// after JOIN THE CULT. In a browser it is this full-window screen, shown at the start of a session: the full panel is NOT mounted
// before the click. Flow: launcher (fade-in) -> JOIN THE CULT -> neural intro -> Main Menu Neural City.
import { useEffect, useRef, useState } from "react";
import { navigate } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import "./launcher.css";

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

const BG = "/assets/neural/launcher-speech.webp";
const SCENE = "/assets/neural/neural-city-scene.webp";

/** Preload the main menu scene before the launcher hides (a failed load is not fatal - the menu shows its own fallback fill). */
function preload(src: string, ms: number): Promise<void> {
  return new Promise((res) => {
    const im = new Image();
    const t = setTimeout(res, ms);
    im.onload = im.onerror = () => { clearTimeout(t); res(); };
    im.src = src;
  });
}

// 1.34 TASK 001: the delivered image of Pepe speaking to the crowd is the full background (proportions kept), JOIN THE CULT in the lower
// centre (hover, click animation, glow), fade-in. The launcher hides only after the switch to the main application succeeded; a lost
// engine connection keeps it visible with the reason and the button active again.
export default function Launcher({ onJoin }: { onJoin: () => void }) {
  const { s } = useStore();
  const [shown, setShown] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [pressed, setPressed] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const t = setTimeout(() => setShown(true), 30);
    return () => clearTimeout(t);
  }, []);
  const ready = !!s.loaded && s.ws === "OPEN";
  const wsRef = useRef(s.ws);
  wsRef.current = s.ws;                                         // the latest connection state (checked after the preload)
  const join = async () => {
    if (!ready || leaving || pressed) return;
    setErr(null);
    setPressed(true);
    await preload(SCENE, 1500);
    if (wsRef.current !== "OPEN") {
      setPressed(false);
      setErr("Połączenie z silnikiem bota zostało przerwane – spróbuj ponownie za chwilę.");
      return;
    }
    try {
      markJoined();
      setLeaving(true);
      setTimeout(() => {
        try { navigate("menu", { params: { intro: "1" } }); onJoin(); }
        catch (e) { setLeaving(false); setPressed(false); setErr(`Nie udało się otworzyć głównej aplikacji: ${String(e)}`); }
      }, 550);
    } catch (e) {
      setPressed(false);
      setErr(`Nie udało się otworzyć głównej aplikacji: ${String(e)}`);
    }
  };
  return (
    <div className={cls("lj", shown && "in", leaving && "out")} data-testid="cult-launcher">
      <div className="lj-fill" aria-hidden="true" />
      <img className="lj-bg" src={BG} alt="Pepe przemawia do zgromadzenia" draggable={false} />
      <div className="lj-shade" aria-hidden="true" />
      <header className="lj-head">
        <div className="lj-brand"><b>PEPEMARKETWIZARD</b><small>AI TRADING INTELLIGENCE</small></div>
        <span className="lj-ver" data-testid="cult-launcher-ver">v{s.app_version ?? "—"} LAUNCHER</span>
      </header>
      <div className="lj-bottom">
        {err && <p className="lj-err" role="alert" data-testid="cult-error">{err}</p>}
        <button type="button" className={cls("lj-join", pressed && "pressed")} onClick={join} disabled={!ready || pressed} data-testid="cult-join" autoFocus>
          JOIN THE CULT<span className="lj-arr" aria-hidden="true">»</span></button>
        <p className={cls("lj-status", ready ? "ok" : "wait")} role="status" data-testid="cult-status">
          <i />{pressed ? "OTWIERANIE PANELU…" : ready ? "SYSTEM READY" : s.loaded ? `ŁĄCZENIE Z SILNIKIEM… (${s.ws ?? "?"})` : "ŁĄCZENIE Z SILNIKIEM…"}</p>
      </div>
    </div>);
}
