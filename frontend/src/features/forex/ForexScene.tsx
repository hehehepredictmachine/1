// Ekran FOREX 1.42 (E2): jeden komponent dla #/forex i #/forex?s=… – zmiana s NIE remontuje sceny (silnik WebGL żyje, otwiera
// i zamyka ekran planety). Przelot z menu: ?from=menu + poza planety z menu (sessionStorage), potem parametr from jest usuwany.
// Panele (S3 §1):
//  MODEL A = praca modeli predykcji: GET /api/v1/models/predictions co 15 s; ANALIZA gdy ≥1 pozycja READY, OCZEKUJE gdy są pozycje,
//            BRAK DANYCH gdy lista pusta, BŁĄD przy błędzie HTTP; impuls przy nowszym data_time / created_at którejkolwiek pozycji READY.
//  MODEL B = silnik sygnałów: zdarzenia bar_closed ze store + GET /api/v1/bot-signals?limit=1 co 10 s; ANALIZA gdy WebSocket OPEN
//            i bar_closed w ostatnich 2 × TF, OCZEKUJE w innym razie, BŁĄD bez połączenia; łańcuch do rdzenia przy nowym sygnale.
import { useEffect, useRef, useState } from "react";
import { apiGet } from "../../api";
import { navigate, type ForexScreen, FOREX_SCREENS } from "../../router";
import { useStore } from "../../store";
import { prefersReducedMotion } from "../cinematic/introGate";
import { ExecStatus, SystemIcons } from "../system/SystemBar";
import type { SysPanel } from "../system/SystemDrawer";
import { mountForex } from "./engine/forexEngine";
import { usePoll } from "./data";
import ChartsScreen, { type ChartsApi } from "./screens/charts/ChartsScreen";
import SignalsScreen from "./screens/SignalsScreen";
import ModelsScreen from "./screens/ModelsScreen";
import RoiScreen from "./screens/RoiScreen";
import "./forex.css";

export const POSE_KEY = "pmw.forex.pose";
const NAMES = ["CHARTS", "SIGNALS", "MODELS & BACKTEST", "ROI"];

export type ScreenProps = { engine: any; active: boolean; onSystem(p: SysPanel): void };

export default function ForexScene({ screen, fromMenu, onSystem, testMode }: { screen: ForexScreen | null; fromMenu: boolean; onSystem(p: SysPanel): void; testMode?: boolean }) {
  const { s } = useStore();
  const root = useRef<HTMLDivElement>(null);
  const eng = useRef<any>(null);
  const [noGl, setNoGl] = useState(false);
  const [sub, setSub] = useState<{ state: string; i: number }>({ state: "none", i: -1 });
  const [phase, setPhase] = useState("dive");
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const prof = usePoll<any>(testMode ? null : "/api/v1/baskets/settings", 30000);
  const charts = useRef<ChartsApi | null>(null);

  // ---- silnik (montowany raz)
  useEffect(() => {
    let pose: any = null;
    try { const p = sessionStorage.getItem(POSE_KEY); if (p && fromMenu) pose = JSON.parse(p); sessionStorage.removeItem(POSE_KEY); } catch { /* brak */ }
    const e: any = mountForex(root.current!, {
      fromMenu, startPose: pose, reduced: prefersReducedMotion(),
      onNoWebGL: () => setNoGl(true),
      onPhase: (ph: string) => setPhase(ph),
      onChoose: (i: number) => navigate("forex", { params: { s: FOREX_SCREENS[i] } }),
      onBackFromSub: () => navigate("forex"),
      onSurfaced: () => navigate("menu"),
      onSubState: (st: string, i: number) => setSub({ state: st, i }),
      escBlocked: () => !!document.querySelector(".sys-layer"),
      screens: charts.current ? { 0: charts.current } : {},                 // CHARTS 1:1 – ekran z własnym rysowaniem (jak SCREENS[0] wzorca)
    });
    eng.current = e;
    if (fromMenu) history.replaceState(null, "", location.hash.replace(/([?&])from=menu&?/, "$1").replace(/[?&]$/, ""));
    const w = window as any;
    if (w.navigator?.webdriver) { w.__PMW_E2E__ = w.__PMW_E2E__ || {}; w.__PMW_E2E__.forex = { state: () => e.state(), result: (i: number) => e.result(i), chartsPerf: () => charts.current?.perf() }; }
    if (import.meta.env.MODE === "test" && testMode) {   // tryb testowy 1:1 (tylko charts-test.html): jak PMW_PREVIEW._seek / _charts / _chartsLoad wzorca
      e.testSeek("menu", 0);
      w.__PMW_TEST__ = w.__PMW_TEST__ || {};
      w.__PMW_TEST__.charts = {
        enter: () => { e.testSeek("forex", 1); e.testSub(0, 1); },
        load: (fx: any) => new Promise<void>((res) => { if (e.state().sub !== "on") { e.testSeek("forex", 1); e.testSub(0, 1); } charts.current?.load(fx); requestAnimationFrame(() => requestAnimationFrame(() => res())); }),
        state: () => charts.current?.state(),
      };
    }
    return () => { e.dispose(); eng.current = null; if (w.__PMW_E2E__) delete w.__PMW_E2E__.forex; if (import.meta.env.MODE === "test" && w.__PMW_TEST__) delete w.__PMW_TEST__.charts; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- trasa ?s=… -> ekran planety (bez remontu sceny)
  useEffect(() => {
    const e = eng.current;
    if (!e) return;
    const i = screen ? FOREX_SCREENS.indexOf(screen) : -1;
    if (i >= 0) e.openSub(i); else e.closeSub();
  }, [screen, noGl]);

  // ---- ograniczenie ruchu z przełącznika (wspólny klucz z menu)
  useEffect(() => {
    const f = () => eng.current?.setReduced(prefersReducedMotion());
    window.addEventListener("storage", f);
    return () => window.removeEventListener("storage", f);
  }, []);

  // ---- MODEL A: predykcje
  const lastPred = useRef<number>(0);
  useEffect(() => {
    if (testMode) return;
    let alive = true;
    const tick = () => apiGet<any>("/api/v1/models/predictions?instrument=XAUUSD").then((r) => {
      if (!alive) return;
      const items: any[] = r?.items || [];
      const ready = items.filter((x) => x.state === "READY");
      eng.current?.setPanel(0, !items.length ? "nodata" : ready.length ? "working" : "idle");
      const newest = Math.max(0, ...ready.map((x) => Date.parse(x.data_time || "") || (x.created_at ? x.created_at * 1000 : 0)));
      if (newest > lastPred.current) { if (lastPred.current) eng.current?.result(0); lastPred.current = newest; }
    }).catch((e) => alive && eng.current?.setPanel(0, "error", String(e?.message || e).slice(0, 120)));
    tick();
    const t = setInterval(tick, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  // ---- MODEL B: silnik sygnałów
  const lastBarAt = useRef<number>(0);
  const lastSig = useRef<string | null>(null);
  const closedSeq = Object.values(s.barTick || {}).filter((b: any) => b?.closed).map((b: any) => b.seq).join(",");
  useEffect(() => { if (closedSeq) lastBarAt.current = Date.now(); }, [closedSeq]);
  useEffect(() => {
    if (testMode) return;
    let alive = true;
    const tick = () => {
      if (s.ws !== "OPEN") { eng.current?.setPanel(1, "error", "brak połączenia z silnikiem (WebSocket)"); return; }
      eng.current?.setPanel(1, Date.now() - lastBarAt.current < 2 * 300 * 1000 ? "working" : "idle");
      apiGet<any>("/api/v1/bot-signals?limit=1").then((r) => {
        if (!alive) return;
        const id = r?.items?.[0]?.signal_id ?? null;
        if (id && lastSig.current && id !== lastSig.current) eng.current?.result(1);
        if (id) lastSig.current = id;
      }).catch(() => undefined);
    };
    tick();
    const t = setInterval(tick, 10000);
    return () => { alive = false; clearInterval(t); };
  }, [s.ws]);

  const active = prof.data?.active_profile;
  const subI = screen ? FOREX_SCREENS.indexOf(screen) : -1;
  const Screen = [null, SignalsScreen, ModelsScreen, RoiScreen][subI] || null;
  const shown = noGl ? subI : sub.state !== "none" ? sub.i : -1;
  // CHARTS bez WebGL (O1 / K6): silnik kuli jest atrapą, więc ekran rysuje własna pętla – bez animacji przejścia (jak ograniczenie ruchu)
  useEffect(() => {
    const a: any = charts.current;
    if (!noGl || subI !== 0 || !a) return;
    const S0: any = { view: { w: innerWidth, h: innerHeight, dpr: Math.min(devicePixelRatio || 1, 2) }, reduced: true, phase: "static" };
    const SUB0: any = { state: "on", p: 1, pi: 0 };
    a.bind(S0, SUB0); a.screen.open();
    const el = document.getElementById("charts-screen") as any;
    if (el) { el.inert = false; el.style.opacity = "1"; }
    if (root.current) root.current.dataset.sub = "on";                    // CSS ekranu: interakcje .ci jak po wejściu w silniku
    let raf = 0, last = performance.now();
    const loop = (t: number) => {
      S0.view = { w: innerWidth, h: innerHeight, dpr: Math.min(devicePixelRatio || 1, 2) };
      a.screen.draw(t, Math.min(100, t - last)); last = t; raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { cancelAnimationFrame(raf); a.screen.close(); if (el) { el.inert = true; el.style.opacity = "0"; } if (root.current) root.current.dataset.sub = "none"; };
  }, [noGl, subI]);
  const ShownScreen = [null, SignalsScreen, ModelsScreen, RoiScreen][shown] || Screen;
  return (
    <div className="app-forex" data-state="dive" data-sub="none" ref={root} data-testid="page-forex" data-static={noGl ? "1" : undefined}>
      <canvas id="c" aria-hidden="true" />
      <div id="fx-vignette" aria-hidden="true" />
      <main id="fx-menu" aria-hidden="true" inert><button id="forex" type="button" tabIndex={-1} aria-label="Kula FOREX" /></main>
      <section id="forex-screen" aria-label="Tryb FOREX" inert>
        <div className="panel left interactive" id="panelA" tabIndex={0} role="group" data-testid="panel-model-a">
          <div className="view"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" /></div></div>
        <div className="panel right interactive" id="panelB" tabIndex={0} role="group" data-testid="panel-model-b">
          <div className="view"><i className="corner tl" /><i className="corner tr" /><i className="corner bl" /><i className="corner br" /></div></div>
        {NAMES.map((n, i) => (
          <button key={n} className="planet interactive" type="button" data-i={i} aria-label={n} aria-pressed="false" data-testid={"planet-" + FOREX_SCREENS[i]}
            onClick={noGl ? () => navigate("forex", { params: { s: FOREX_SCREENS[i] } }) : undefined}>
            <span className="plabel" aria-hidden="true"><span className="num">{String(i + 1).padStart(2, "0")}</span><span className="pname">{n}</span></span></button>))}
        <button id="fx-return" className="interactive" type="button" aria-label={subI >= 0 ? "Powrót do ekranu FOREX" : "Powrót do menu"} data-testid="forex-back"
          onClick={noGl ? () => (subI >= 0 ? navigate("forex") : navigate("menu")) : undefined}>
          <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M16 10H4m5-5-5 5 5 5" /></svg></button>
      </section>
      <ChartsScreen register={(a) => { charts.current = a; }} active={subI === 0 || (sub.state !== "none" && sub.i === 0)} testMode={testMode} />
      <canvas id="sub-canvas" aria-hidden="true" />
      <div id="sub-screen" inert data-testid="sub-screen">
        {ShownScreen && <ShownScreen engine={eng.current} active={sub.state === "on" || noGl} onSystem={onSystem} />}
      </div>
      {active && active !== "FOREX_MT5" && phase !== "menu" && (
        <div className="fx-profile-warn" role="status">Aktywny profil bota: {active} – ten ekran pokazuje dane FOREX/MT5</div>)}
      <ExecStatus onOpen={onSystem} />
      <SystemIcons onOpen={onSystem} />
      <div id="fx-announcer" className="sr-only" aria-live="polite" />
      {noGl && <div className="fx-static-note" role="status">Renderer 3D jest niedostępny – widok uproszczony, dane i ekrany działają bez efektów.</div>}
    </div>);
}
