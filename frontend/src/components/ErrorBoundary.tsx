// 1.40.3: one error in a screen never blanks the whole window. The boundary shows what broke and lets the user go back to the menu
// or reload; it resets itself when the screen (hash) changes. A screen chunk that cannot be loaded (application updated while the
// window was open) reloads the page once instead of staying empty.
import { Component, useEffect, useState, type ReactNode } from "react";

const CHUNK_RE = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|ChunkLoadError/i;
const RELOAD_KEY = "pmw.chunkReloadAt";

function chunkReloadOnce(msg: string): boolean {
  if (!CHUNK_RE.test(msg)) return false;
  try {
    const last = Number(sessionStorage.getItem(RELOAD_KEY) || 0);
    if (Date.now() - last < 60_000) return false;          // already tried within the last minute: show the error instead of looping
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch { /* storage blocked: reload anyway, once per render of the boundary */ }
  location.reload();
  return true;
}

type Props = { children: ReactNode; resetKey: string };
type State = { err: string | null; stack: string };

class Boundary extends Component<Props, State> {
  state: State = { err: null, stack: "" };

  static getDerivedStateFromError(e: unknown): Partial<State> {
    const err = e instanceof Error ? e : new Error(String(e));
    return { err: err.message || String(e), stack: (err.stack || "").split("\n").slice(0, 6).join("\n") };
  }

  componentDidCatch(e: unknown) {
    const msg = e instanceof Error ? e.message : String(e);
    chunkReloadOnce(msg);
    try {
      console.error("[PMW] błąd ekranu:", e);
    } catch { /* ignore */ }
  }

  componentDidUpdate(prev: Props) {
    if (prev.resetKey !== this.props.resetKey && this.state.err) this.setState({ err: null, stack: "" });
  }

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div className="pmw-crash" role="alert">
        <div className="pmw-crash-box">
          <h2>Ten ekran napotkał błąd</h2>
          <p>Bot i silnik działają dalej – to dotyczy tylko widoku w oknie. Możesz wrócić do menu albo odświeżyć widok.</p>
          <pre>{this.state.err}{this.state.stack ? "\n\n" + this.state.stack : ""}</pre>
          <div className="pmw-crash-row">
            <button type="button" onClick={() => { location.hash = "#/menu"; }}>Menu główne</button>
            <button type="button" onClick={() => location.reload()}>Odśwież</button>
          </div>
        </div>
      </div>
    );
  }
}

function useHash(): string {
  const [h, setH] = useState(() => location.hash.split("?")[0]);
  useEffect(() => {
    const on = () => setH(location.hash.split("?")[0]);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return h;
}

export default function ErrorBoundary({ children }: { children: ReactNode }) {
  const hash = useHash();
  useEffect(() => {
    const onRej = (ev: PromiseRejectionEvent) => {
      const r = ev.reason;
      chunkReloadOnce(r instanceof Error ? r.message : String(r));
    };
    window.addEventListener("unhandledrejection", onRej);
    return () => window.removeEventListener("unhandledrejection", onRej);
  }, []);
  return <Boundary resetKey={hash}>{children}</Boundary>;
}
