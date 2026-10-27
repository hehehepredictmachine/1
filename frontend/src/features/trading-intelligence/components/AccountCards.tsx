// Balance / Equity / open P/L / ROI of the connected MT5 account. Values only from the terminal (WS account) and the engine's ROI
// (modified Dietz over stored equity snapshots, /api/v1/stats). Without data: "—", never 0.
import { useEffect, useState } from "react";
import { apiGet } from "../../../api";
import { useStore } from "../../../store";
import { cls, fmtMoney, fmtNum, fmtTime } from "../../../util";

export default function AccountCards() {
  const { s } = useStore();
  const acc = s.account;
  const linked = s.ws === "OPEN" && s.connection?.state === "CONNECTED" && !!acc;
  const cur = acc?.currency ?? null;
  const [roi, setRoi] = useState<any>(null);
  const mode = s.mode?.mode;
  useEffect(() => {
    let alive = true;
    const m = mode === "AUTO_DEMO" || mode === "AUTO_LIVE" ? mode : "PAPER";
    const load = () => apiGet(`/api/v1/stats?mode=${m}`).then((r: any) => alive && setRoi(r.account_roi ?? null)).catch(() => alive && setRoi(null));
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, [mode, s.symbol?.symbol]);
  const positions = (s.positions?.positions || []).length;
  const src = linked ? `MT5 · ${acc.trade_mode ?? "?"} · ${acc.login ?? ""}` : "MT5 niepołączony";
  const pl = linked ? acc.profit : null;
  return (
    <div className="t-stats" data-testid="ti-account" role="group" aria-label="Rachunek">
      <div className="t-stat" data-testid="ti-balance"><span>Balance</span><b>{linked ? fmtMoney(acc.balance, cur) : "—"}</b><small>{src}</small></div>
      <div className="t-stat" data-testid="ti-equity"><span>Equity</span><b>{linked ? fmtMoney(acc.equity, cur) : "—"}</b>
        <small>{linked ? `wolny margin ${fmtMoney(acc.free_margin, cur)}` : "MT5"}</small></div>
      <div className="t-stat" data-testid="ti-pl"><span>P/L otwartych pozycji</span>
        <b className={cls(pl != null && pl > 0 && "t-pos", pl != null && pl < 0 && "t-neg")}>{pl != null ? fmtMoney(pl, cur) : "—"}</b>
        <small>{linked ? `${positions} ${positions === 1 ? "pozycja" : "pozycji"} na rachunku (wszystkie symbole wg terminala)` : "—"}</small></div>
      <div className="t-stat" data-testid="ti-roi" title={roi?.method ? `${roi.method}. ${roi.scope ?? ""}. ${roi.sampling_note ?? ""}` : undefined}>
        <span>ROI</span>
        <b className={cls(roi?.status === "OK" && roi.roi_pct > 0 && "t-pos", roi?.status === "OK" && roi.roi_pct < 0 && "t-neg")}>
          {roi?.status === "OK" && roi.roi_pct != null ? `${fmtNum(roi.roi_pct, 2)} %` : "—"}</b>
        <small>{roi?.status === "OK" ? `od ${fmtTime(roi.period_from, true)} · metoda modified Dietz · cały rachunek`
          : roi?.note ?? (roi?.status === "NO_ACCOUNT" ? "brak rachunku" : "brak danych")}</small></div>
    </div>);
}
