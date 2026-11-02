// Title band of a tower view: tower name in its accent, role, and the data facts every view needs (source, last update).
import type { CSSProperties, ReactNode } from "react";
import { useStore } from "../../store";
import { fmtTime } from "../../util";
import { useTerminalContext } from "../shell/useTerminalContext";
import { TOWERS, type TowerId } from "./assets";
import { envLabel } from "./WizardShell";

export default function ViewHeader({ tower, children }: { tower: TowerId; children?: ReactNode }) {
  const t = TOWERS.find((x) => x.id === tower)!;
  const { s } = useStore();
  const ctx = useTerminalContext();
  const updated = s.quote?.time_utc ?? s.decision?.as_of_utc ?? null;
  return (
    <header className="wz-view-head" style={{ "--tw": t.accent, "--tw2": t.accent2 } as CSSProperties} data-testid={`wz-head-${tower}`}>
      <div>
        <h1 className="wz-view-title">{t.name}</h1>
        <p className="wz-view-role">{t.role}</p>
      </div>
      <dl className="wz-facts">
        <div><dt>Instrument</dt><dd data-testid="wz-fact-symbol">{ctx.brokerSymbol ?? "—"}{ctx.instrument ? <span className="wz-dim"> ({ctx.instrument})</span> : null}</dd></div>
        <div><dt>Źródło</dt><dd>{ctx.env === "SYNTHETIC" ? "symulator terminala" : ctx.mt5 === "CONNECTED" ? "terminal MT5" : "brak połączenia z MT5"}
          <span className="wz-dim"> · {envLabel(ctx.env)}</span></dd></div>
        <div><dt>Ostatnia aktualizacja</dt><dd data-testid="wz-fact-updated">{updated && ctx.backend === "OPEN" ? fmtTime(updated, true) : "—"}
          <span className="wz-dim"> · {ctx.freshnessDetail}</span></dd></div>
      </dl>
      {children}
    </header>);
}
