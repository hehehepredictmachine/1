// MAIN MENU (menu.jpg) + MAIN MENU MOTION SYSTEM (instrukcja.jpg). The scene is the approved artwork split into layers (scene, city,
// energy core, six towers, four Pepe wizards, element effects); the brand, slogan, menu, notifications, profile and the four live
// values are drawn in HTML. Every tower is its own interactive entry (hover: light + energy pulse + preview, click: camera zoom and
// the panel). Intro "HYBRID CINEMATIC" 6 s (storyboard in cult.css, phases 0.0-6.0 s): darkness -> logo -> city -> core -> towers ->
// wizards with element effects -> slogan and full menu. Idle: gentle motion of the wizards. Live data: values update in place.
// Reduced motion: no intro sequence, no idle motion, no zoom. Navigation only - nothing here changes the bot.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { href, navigate, type Page, type Route } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { A, CHAR_BOX, FX_BOX, TOWER_BOX, box, type TowerKey } from "./assets";
import { LeftPanel, MENU_NAV, Strips, TopRight } from "./CultShell";
import { kindOf, money, pct, signed, useEnvKind, useGet } from "./data";
import { Stat, StatusBar } from "./kit";
import "./cult.css";

type TowerDef = { key: TowerKey; page: Page; name: string; role: string; color: string; desc: string };
export const MENU_TOWERS: TowerDef[] = [
  { key: "lightning", page: "lightning", name: "Lightning Tower", role: "Live Signals", color: "#ffcc4d", desc: "Sygnały BUY/SELL wszystkich strategii, plan wejścia, cykl życia sygnału i alerty rynku." },
  { key: "ice", page: "precision", name: "Ice Tower", role: "Analytics", color: "#6fd8ff", desc: "Wykresy MT5, interwały, reżim, strefy i analiza rynku (widok Precision)." },
  { key: "wind", page: "wind", name: "Wind Portal", role: "AI Engine", color: "#39ff8f", desc: "Modele AI, konsensus bez łączenia różnych jednostek, Monte Carlo, ślad decyzji." },
  { key: "control", page: "control", name: "Control Tower", role: "Bot Management", color: "#ffb347", desc: "Wyniki, sterowanie strategią, ryzyko, Telegram, jakość danych, autopilot, infrastruktura, audyt." },
  { key: "strategy", page: "strategy-lab", name: "Strategy Lab", role: "Strategy Development", color: "#b46bff", desc: "Komora strategii: silnik, ustawienia, budowniczy (podgląd potoku decyzji), biblioteka, porównanie." },
  { key: "fire", page: "trading-intelligence", name: "Fire Tower", role: "Trading Terminal", color: "#ff6a2b", desc: "Terminal handlowy: rynek, scenariusze, sygnały, pozycje (Trading Intelligence)." },
];

function prefersReduced(): boolean {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

function useMenuData() {
  const env = useEnvKind();
  const { s } = useStore();
  const stats = useGet<any>("/api/v1/stats", 20000);
  const sig = useGet<any>("/api/v1/bot-signals?limit=200", 15000);
  const cat = useGet<any>("/api/v1/models/catalog", 60000);
  const all = stats.d?.bot?.all;
  const roi = stats.d?.account_roi;
  const active = (sig.d?.items || []).filter((x: any) => x.status === "OPEN" || x.status === "ACTIVE" || x.status === "PENDING").length;
  return {
    env, stats, sig, cat, cur: s.account?.currency ?? stats.d?.bot?.currency,
    pl: roi?.status === "OK" && roi.roi_pct != null ? { v: pct(roi.roi_pct, 2), sub: `ROI 30 dni (Dietz) · netto ${signed(all?.net)}` }
      : { v: all && all.trades ? signed(all.net) : "—", sub: all?.trades ? `${all.trades} transakcji (netto)` : "brak rozliczonych transakcji" },
    wr: all?.win_rate != null ? { v: pct(all.win_rate), sub: `${all.wins ?? "?"} / ${(all.wins ?? 0) + (all.losses ?? 0)} (bez BE)` } : { v: "—", sub: "brak danych" },
    active: sig.d ? { v: String(active), sub: `${sig.d.items?.length ?? 0} w historii` } : { v: "—", sub: sig.err ? "błąd" : "…" },
    aum: s.account?.equity != null ? { v: money(s.account.equity, s.account.currency), sub: "equity rachunku MT5" } : { v: "—", sub: "brak rachunku" },
  };
}

function preview(k: TowerKey, m: ReturnType<typeof useMenuData>, s: any): string {
  const ready = m.cat.d ? `${m.cat.d.counts_by_state?.READY ?? 0} gotowych modułów` : "…";
  switch (k) {
    case "lightning": return `Aktywne sygnały: ${m.active.v}`;
    case "ice": return `${s.symbol?.symbol ?? "—"} · dane ${s.decision?.data_quality ?? "—"}`;
    case "wind": return `Katalog modeli: ${ready}`;
    case "control": return `Tryb: ${s.mode?.mode_label ?? s.mode?.mode ?? "—"}${s.mode?.kill_switch ? " · STOP" : ""}`;
    case "strategy": return `Strategia: ${s.auto?.selected_strategy_id ?? "—"} (${s.auto?.strategy_mode ?? s.decision?.setup?.strategy_id ?? "AUTO"})`;
    case "fire": return `Pozycje: ${(s.positions || []).length}`;
  }
}

export default function CultMenu({ route }: { route: Route }) {
  const { s } = useStore();
  const reduced = useMemo(prefersReduced, []);
  const [intro, setIntro] = useState(() => route.params.get("intro") === "1" && !reduced);
  const [hover, setHover] = useState<TowerKey | null>(null);
  const [zoom, setZoom] = useState<TowerDef | null>(null);
  const m = useMenuData();
  const stage = useRef<HTMLDivElement>(null);
  useEffect(() => {
    document.documentElement.classList.add("cu-doc");
    return () => document.documentElement.classList.remove("cu-doc");
  }, []);
  useEffect(() => {
    if (route.params.get("intro") === "1") {
      navigate("menu", { replace: true });                                // the intro is played once; refresh shows the menu
    }
    if (!intro) return;
    const end = () => setIntro(false);
    const t = setTimeout(end, 6200);
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") end(); };
    window.addEventListener("keydown", k);
    return () => { clearTimeout(t); window.removeEventListener("keydown", k); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intro]);
  const open = useCallback((t: TowerDef) => {
    if (zoom) return;
    if (reduced) { navigate(t.page); return; }
    setZoom(t);
    setTimeout(() => navigate(t.page), 720);
  }, [zoom, reduced]);
  const zb = zoom ? TOWER_BOX[zoom.key] : null;
  const zoomStyle: CSSProperties = zb ? { transformOrigin: `${(((zb[0] + zb[2]) / 2 - 236) / 1300) * 100}% ${(((zb[1] + zb[3]) / 2) / 708) * 100}%` } : {};
  const hv = MENU_TOWERS.find((t) => t.key === hover);
  return (
    <div className={cls("cm", intro && "intro", reduced && "reduced", zoom && "zooming")} data-testid="page-menu" data-intro={intro ? "1" : "0"}>
      <div className="cm-fill" aria-hidden="true" style={{ backgroundImage: `url(${A.sceneBlur})` }} />
      <div className="cm-layout">
        <LeftPanel page="menu" nav={MENU_NAV} />
        <div className="cm-main">
          <header className="cm-top">
            <div className="cm-title">
              <img className="cm-crown" src={A.crown} alt="" />
              <p className="cm-brand">PEPEMARKETWIZARD</p>
              <p className="cm-tagline">ALGORITHMIC TRADING INTELLIGENCE</p>
              <h1 className="cm-slogan" data-testid="cm-slogan">THEY CALL US CULT BUT WE ARE SOMETHING MUCH MORE</h1>
              <p className="cm-orn" aria-hidden="true"><i />◆<i /></p>
            </div>
            <TopRight />
          </header>
          <Strips />
          <div className="cm-stage-wrap">
            <div className="cm-stage" ref={stage} style={zoomStyle} data-testid="cm-stage">
              <img className="cm-base" src={A.scene} alt="Miasto PepeMarketWizard z sześcioma wieżami i czterema czarodziejami Pepe" draggable={false} />
              <img className="cm-l cm-city" src={A.fx("city")} style={box(FX_BOX.city)} alt="" aria-hidden="true" />
              <span className="cm-l cm-core" style={box(FX_BOX.core)} aria-hidden="true"><img src={A.fx("core")} alt="" /><i /></span>
              {(["lightning", "ice", "wind", "fire", "king"] as const).map((c, i) => (
                <img key={c} className={cls("cm-l cm-char", `c-${c}`)} src={A.char(c)} style={{ ...box(CHAR_BOX[c]), "--i": i } as CSSProperties} alt="" aria-hidden="true" />))}
              <img className="cm-l cm-fx fx-bolt" src={A.fx("lightning")} style={box(FX_BOX.lightning)} alt="" aria-hidden="true" />
              <img className="cm-l cm-fx fx-flame" src={A.fx("fire")} style={box(FX_BOX.fire)} alt="" aria-hidden="true" />
              <img className="cm-l cm-fx fx-ice" src={A.fx("ice_crystal")} style={box(FX_BOX.ice_crystal)} alt="" aria-hidden="true" />
              <img className="cm-l cm-fx fx-swirl" src={A.fx("wind_swirl")} style={box(FX_BOX.wind_swirl)} alt="" aria-hidden="true" />
              <svg className="cm-l cm-sparks" viewBox="0 0 1300 708" aria-hidden="true">
                <path className="bolt b1" d="M232 230 l-14 34 l12 -2 l-16 40" /><path className="bolt b2" d="M262 214 l10 30 l-10 0 l14 36" />
                {[[500, 175], [520, 210], [486, 236], [548, 190], [470, 205]].map(([x, y], i) => <circle key={i} className="spark" cx={x} cy={y} r="2.6" style={{ "--i": i } as CSSProperties} />)}
                <ellipse className="swirl s1" cx="768" cy="210" rx="150" ry="44" /><ellipse className="swirl s2" cx="768" cy="215" rx="120" ry="30" />
              </svg>
              {MENU_TOWERS.map((t, i) => (
                <img key={t.key} className={cls("cm-l cm-tower", `t-${t.key}`, hover === t.key && "hot")} src={A.tower(t.key)} alt=""
                  style={{ ...box(TOWER_BOX[t.key]), "--tc": t.color, "--i": i } as CSSProperties} aria-hidden="true" />))}
              {MENU_TOWERS.map((t) => (
                <a key={t.key} href={href(t.page)} className="cm-hot" style={box(TOWER_BOX[t.key])} data-testid={`cm-tower-${t.key}`} data-page={t.page}
                  aria-label={`${t.name} – ${t.role}. ${t.desc}`}
                  onMouseEnter={() => setHover(t.key)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(t.key)} onBlur={() => setHover(null)}
                  onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey) { e.preventDefault(); open(t); } }} />))}
              {hv && !zoom && (
                <div className="cm-prev" style={{ ...box(TOWER_BOX[hv.key]), "--tc": hv.color } as CSSProperties} role="status" data-testid="cm-preview">
                  <b>{hv.name}</b><small>{hv.role}</small><p>{hv.desc}</p><em>{preview(hv.key, m, s)}</em></div>)}
              {zoom && <div className="cm-portal" style={{ "--tc": zoom.color } as CSSProperties} aria-hidden="true" />}
            </div>
          </div>
          <StatusBar testid="cm-stats" centre={<img src={A.medallion} alt="" />}>
            <Stat icon="chart" label="TOTAL P/L" value={m.pl.v} sub={m.pl.sub} kind={kindOf(m.stats, m.env, !!m.stats.d?.bot?.all?.trades || m.stats.d?.account_roi?.status === "OK")} testid="cm-pl" />
            <Stat icon="bars" label="WIN RATE" value={m.wr.v} sub={m.wr.sub} kind={kindOf(m.stats, m.env, m.stats.d?.bot?.all?.win_rate != null)} testid="cm-wr" />
            <span className="cu-sbar-gap" aria-hidden="true" />
            <Stat icon="signal" label="ACTIVE SIGNALS" value={m.active.v} sub={m.active.sub} kind={kindOf(m.sig, m.env)} testid="cm-active" />
            <Stat icon="coins" label="AUM (TRADING)" value={m.aum.v} sub={m.aum.sub} kind={s.account?.equity != null ? m.env : "NONE"} testid="cm-aum" />
          </StatusBar>
        </div>
      </div>
      {intro && (
        <>
          <div className="ci-dark" aria-hidden="true" />
          <div className="ci-logo" aria-hidden="true"><img src={A.crown} alt="" /><span>P</span><b>PEPEMARKETWIZARD</b></div>
          <button type="button" className="ci-skip" onClick={() => setIntro(false)} data-testid="cm-skip">Pomiń intro ›</button>
        </>)}
      <p className="cm-sr" aria-live="polite">{intro ? "Intro PepeMarketWizard" : ""}</p>
    </div>);
}
