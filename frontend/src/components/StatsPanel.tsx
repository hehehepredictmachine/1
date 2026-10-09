import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { useStore } from "../store";
import { cls, epochSec, fmtNum } from "../util";

const MODES = [["PAPER", "PAPER"], ["AUTO_DEMO", "DEMO"], ["AUTO_LIVE", "LIVE"]] as const;

export default function StatsPanel({ index, stats, mode, setMode }: { index: number; stats: any; mode: string; setMode: (m: string) => void }) {
  const { s } = useStore();
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const area = useRef<ISeriesApi<"Area"> | null>(null);
  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#8fd8ad", fontSize: 10, attributionLogo: true },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(40,255,140,0.06)" } },
      rightPriceScale: { borderColor: "#124d2c" },
      timeScale: { borderColor: "#124d2c", timeVisible: true },
      handleScroll: false,
      handleScale: false,
    });
    chart.current = c;
    area.current = c.addSeries(AreaSeries, { lineColor: "#2bff88", topColor: "rgba(43,255,136,0.35)", bottomColor: "rgba(43,255,136,0.02)", lineWidth: 2 });
    return () => c.remove();
  }, []);
  useEffect(() => {
    const pts = stats?.equity?.points || [];
    const shift = -new Date().getTimezoneOffset() * 60;
    const seen = new Set<number>();
    const data = pts.map((p: any) => ({ time: (epochSec(p.ts) + shift) as Time, value: p.equity }))
      .filter((p: any) => (seen.has(p.time as number) ? false : (seen.add(p.time as number), true)));
    area.current?.setData(data);
    chart.current?.timeScale().fitContent();
  }, [stats]);
  const b = stats?.bot;
  const all = b?.all;
  const cur = b?.currency || s.account?.currency || "";
  const val = (x: any, suf = "") => (x === null || x === undefined ? "brak danych" : `${fmtNum(x)}${suf}`);
  return (
    <div className="panel">
      <div className="panel-head">
        <span className="pnum">{index}</span>
        <span className="ptitle">BOT STATISTICS & PERFORMANCE</span>
        <span className="spacer" />
        <div className="tabs small">
          {MODES.map(([m, l]) => <button key={m} className={cls(mode === m && "on")} onClick={() => setMode(m)}>{l}</button>)}
        </div>
      </div>
      <div className="stats-grid">
        <div className="stats-main">
          <label>WYNIK NETTO BOTA ({mode === "PAPER" ? "PAPER" : mode === "AUTO_DEMO" ? "DEMO" : "LIVE"})</label>
          <b className={cls("big", (all?.net ?? 0) >= 0 ? "pos" : "neg")}>{all?.trades ? `${fmtNum(all.net)} ${cur}` : "brak danych"}</b>
          <div className="eq-label">{stats?.equity?.label ?? ""}</div>
          <div className={cls("eq-box", stats?.equity?.status !== "OK" && "empty")} ref={box} />
          {stats?.equity?.status !== "OK" && <div className="chart-msg">Brak zapisanych snapshotów equity (zapis co 60 s od uruchomienia).</div>}
        </div>
        <div className="stat"><label>WIN RATE</label><b>{val(all?.win_rate, "%")}</b></div>
        <div className="stat"><label>PROFIT FACTOR</label><b>{val(all?.profit_factor)}</b></div>
        <div className="stat"><label>TRANSAKCJE</label><b>{all?.trades ?? 0}</b><small>{all?.status === "SMALL_SAMPLE" ? "mała próba" : ""}</small></div>
        <div className="stat"><label>DZIEŃ</label><b className={(b?.day?.net ?? 0) >= 0 ? "pos" : "neg"}>{b?.day?.trades ? fmtNum(b.day.net) : "—"}</b></div>
        <div className="stat"><label>TYDZIEŃ</label><b className={(b?.week?.net ?? 0) >= 0 ? "pos" : "neg"}>{b?.week?.trades ? fmtNum(b.week.net) : "—"}</b></div>
        <div className="stat"><label>MIESIĄC</label><b className={(b?.month?.net ?? 0) >= 0 ? "pos" : "neg"}>{b?.month?.trades ? fmtNum(b.month.net) : "—"}</b></div>
        <div className="stat wide"><label>RACHUNEK MT5 (wszystkie operacje, 30 dni)</label>
          <b>{stats?.account ? `${fmtNum(stats.account.trading_net_all_symbols)} ${s.account?.currency ?? ""}` : "—"}</b>
          <small>wpłaty/wypłaty osobno: {stats?.account ? fmtNum(stats.account.balance_operations) : "—"}</small></div>
      </div>
    </div>
  );
}
