// „Pepe Training Studio” – przycisk w menu bota ze stanem (1.33). Studio działa jako OSOBNY proces (port 8780) i nigdy nie wysyła zleceń.
import { useState } from "react";
import { apiSend } from "../../api";
import { cls } from "../../util";
import { usePoll } from "./usePoll";

export default function StudioButton({ variant = "chip" }: { variant?: "chip" | "nav" }) {
  const st = usePoll<any>("/api/v1/studio/status", 8000);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const on = !!st.data?.running;
  const open = async () => {
    setErr(null);
    if (on) { window.open(st.data.url, "_blank", "noopener"); return; }
    setBusy(true);
    try {
      const r = await apiSend("POST", "/api/v1/studio/launch");
      for (let i = 0; i < 40; i++) {
        await new Promise((res) => setTimeout(res, 500));
        await st.reload();
        const s2 = await fetch("/api/v1/studio/status", { credentials: "same-origin" }).then((x) => x.json()).catch(() => null);
        if (s2?.running) { if (r.launcher !== "EXE") window.open(s2.url, "_blank", "noopener"); break; }
      }
    } catch (e: any) { setErr(String(e?.message || e)); }
    setBusy(false);
  };
  const label = busy ? "Studio: uruchamianie…" : on ? "Studio ●" : "Studio";
  const title = `Pepe Data & Training Studio – ${on ? `działa (${st.data?.url})` : "nie działa – kliknij, aby uruchomić osobny proces"}${err ? ` · błąd: ${err}` : ""}`;
  return variant === "nav" ?
    <button type="button" className={cls("cu-nav-i", "pmw-studio-nav", on && "on")} onClick={open} title={title} data-testid="studio-button" data-running={on ? "1" : "0"}>
      <span aria-hidden="true">⚗</span><span>Training Studio<small>{busy ? "uruchamianie…" : on ? "działa" : "uruchom"}</small></span></button> :
    <button type="button" className={cls("tb-btn", on && "on")} onClick={open} title={title} data-testid="studio-button" data-running={on ? "1" : "0"} disabled={busy}>{label}</button>;
}
