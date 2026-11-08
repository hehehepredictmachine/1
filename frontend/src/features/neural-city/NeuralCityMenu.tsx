// MAIN MENU – Neural City V7.0 (PepeMarketWizard_NeuralCity_MainMenu_V7_0). The scene is the approved artwork (neural Pepe at the
// holographic table with seven towers) with the old baked labels / example numbers removed (tools/neural_city_assets.py); names,
// navigation, the three account values, the slogan and every effect are drawn live on top of it.
//
// HONEST SCOPE: this is the 2.5D fallback of the brief - the towers are pixels of the artwork, NOT 3D geometry, and Pepe has no rig.
// Animated: hologram rings at the base of every tower (independent speeds, hover slow-down, stop on select), neural particles and
// current on the table, the core reacting to the selected tower, a stylised light path from Pepe's hands to the tower (marked 2.5D),
// the portal and a camera fly-in. The menu only navigates to the EXISTING panels (towers.ts) - it never builds, replaces or changes a
// panel, never opens or closes an order and shows no invented statistics (values from the bot or N/A with the data source marker).
//
// One controller for the top navigation, the tower geometry and the keyboard: IDLE -> SELECTED -> STOP_ROTATION -> PEPE_REACH ->
// CONTACT -> PORTAL -> NAVIGATE (-> RETURN when the menu is opened again). Double click is debounced, Esc cancels, the selected tower
// gets the focus back after returning. Reduced motion / "Wstrzymaj" / Performance: no sequence, direct navigation.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { navigate, type Route } from "../../router";
import { useStore } from "../../store";
import { cls } from "../../util";
import { kindOf, money, pct as fpct, useEnvKind, useGet } from "../cult/data";
import { Tag } from "../cult/kit";
import { CORE, HANDS, SCENE_H, SCENE_W, TOWERS, boxStyle, pct, type Tower } from "./towers";
import "./neural-city.css";

const ASSET = "/assets/neural/";
export type Phase = "INTRO" | "IDLE" | "SELECTED" | "STOP_ROTATION" | "PEPE_REACH" | "CONTACT" | "PORTAL" | "NAVIGATE" | "RETURN";
type Quality = "cinematic" | "balanced" | "performance";
type Prefs = { quality: Quality; parallax: boolean; particles: boolean; intro: boolean };
const PREFS_KEY = "mq.neuralCity.prefs";
const LAST_KEY = "mq.neuralCity.last";
const DEF: Prefs = { quality: "cinematic", parallax: true, particles: true, intro: true };
// ms from the click for each phase; scaled by the quality (Performance and reduced motion skip the sequence)
const SEQ: [Phase, number][] = [["SELECTED", 0], ["STOP_ROTATION", 140], ["PEPE_REACH", 420], ["CONTACT", 980], ["PORTAL", 1180], ["NAVIGATE", 1780]];
const SCALE: Record<Quality, number> = { cinematic: 1, balanced: 0.7, performance: 0 };

function loadPrefs(): Prefs {
  try { return { ...DEF, ...JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") }; } catch { return DEF; }
}
function reducedMotion(): boolean {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
}

function useHud() {
  const env = useEnvKind();
  const { s } = useStore();
  const stats = useGet<any>("/api/v1/stats", 20000);
  const all = stats.d?.bot?.all;
  const roi = stats.d?.account_roi;
  const eqKind = s.account?.equity != null ? (env === "STALE" ? "STALE" : env) : "NONE";
  return [
    { key: "wr", label: "Winratio", value: all?.win_rate != null ? fpct(all.win_rate) : "N/A",
      sub: all?.win_rate != null ? `${all.wins ?? "?"} / ${(all.wins ?? 0) + (all.losses ?? 0)} transakcji bota (bez BE)` : "brak rozliczonych transakcji",
      kind: kindOf(stats, env, all?.win_rate != null) },
    { key: "roi", label: "ROI", value: roi?.status === "OK" && roi.roi_pct != null ? fpct(roi.roi_pct, 2) : "N/A",
      sub: roi?.status === "OK" ? "30 dni, metoda Dietza (wpłaty i wypłaty wyłączone)" : (roi?.reason || "brak historii rachunku"),
      kind: kindOf(stats, env, roi?.status === "OK") },
    { key: "eq", label: "Equity", value: s.account?.equity != null ? money(s.account.equity) : "N/A",
      sub: s.account?.equity != null ? `${s.account.currency ?? ""} · rachunek MT5 (terminal)` : "rozłączono / brak rachunku", kind: eqKind },
  ] as const;
}

/** Neural particles + current on the table (canvas, paused when hidden / paused / Performance). */
function useParticles(ref: React.RefObject<HTMLCanvasElement | null>, on: boolean, quality: Quality, target: Tower | null) {
  const tgt = useRef<Tower | null>(null);
  tgt.current = target;
  useEffect(() => {
    const c = ref.current;
    if (!c || !on || quality === "performance") return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    let raf = 0, w = 0, h = 0;
    const n = quality === "cinematic" ? 110 : 55;
    const P = Array.from({ length: n }, () => ({ x: Math.random(), y: 0.3 + Math.random() * 0.7, v: 0.0004 + Math.random() * 0.0012, r: 0.6 + Math.random() * 1.6, a: Math.random() }));
    const pulses: { t: Tower; p: number; s: number }[] = [];
    let last = performance.now(), spawn = 0;
    const size = () => {
      const r = c.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, quality === "cinematic" ? 2 : 1);
      w = c.width = Math.max(1, Math.round(r.width * dpr)); h = c.height = Math.max(1, Math.round(r.height * dpr));
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(c);
    const frame = (now: number) => {
      const dt = Math.min(64, now - last); last = now;
      ctx.clearRect(0, 0, w, h);
      if (!document.hidden) {
        ctx.globalCompositeOperation = "lighter";
        for (const p of P) {                                         // particles rising over the table
          p.y -= p.v * dt * 0.06; p.a += dt * 0.002;
          if (p.y < 0.08) { p.y = 0.95; p.x = Math.random(); }
          const al = 0.25 + 0.35 * Math.abs(Math.sin(p.a));
          ctx.fillStyle = `rgba(80,255,150,${al})`;
          ctx.beginPath(); ctx.arc(p.x * w, p.y * h, p.r * (w / SCENE_W) * 1.4, 0, Math.PI * 2); ctx.fill();
        }
        spawn -= dt;                                                  // current: pulses from the core to the towers
        if (spawn <= 0) { pulses.push({ t: tgt.current ?? TOWERS[Math.floor(Math.random() * TOWERS.length)], p: 0, s: 0.0009 + Math.random() * 0.0007 }); spawn = tgt.current ? 120 : 520; }
        for (let i = pulses.length - 1; i >= 0; i--) {
          const q = pulses[i]; q.p += q.s * dt;
          if (q.p >= 1) { pulses.splice(i, 1); continue; }
          const x = (CORE[0] + (q.t.ring[0] - CORE[0]) * q.p) / SCENE_W * w, y = (CORE[1] + (q.t.ring[1] - CORE[1]) * q.p) / SCENE_H * h;
          const g = ctx.createRadialGradient(x, y, 0, x, y, 9 * (w / SCENE_W) * 1.5);
          g.addColorStop(0, "rgba(180,255,220,.95)"); g.addColorStop(1, "rgba(57,255,143,0)");
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 9 * (w / SCENE_W) * 1.5, 0, Math.PI * 2); ctx.fill();
        }
        ctx.globalCompositeOperation = "source-over";
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); ro.disconnect(); ctx.clearRect(0, 0, w, h); };
  }, [ref, on, quality]);
}

export default function NeuralCityMenu({ route }: { route: Route }) {
  const reduced = useMemo(reducedMotion, []);
  const [prefs, setPrefsState] = useState<Prefs>(loadPrefs);
  const setPrefs = (p: Prefs) => { setPrefsState(p); try { localStorage.setItem(PREFS_KEY, JSON.stringify(p)); } catch { /* storage unavailable */ } };
  const [paused, setPaused] = useState(false);
  const animate = !reduced && !paused && prefs.quality !== "performance";
  const wantIntro = route.params.get("intro") === "1" && prefs.intro && !reduced;
  const [phase, setPhase] = useState<Phase>(wantIntro ? "INTRO" : "IDLE");
  const [sel, setSel] = useState<Tower | null>(null);
  const [hover, setHover] = useState<Tower | null>(null);
  const [panel, setPanel] = useState<"settings" | "info" | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const hud = useHud();
  const timers = useRef<number[]>([]);
  const busy = useRef(false);
  const stage = useRef<HTMLDivElement>(null);
  const cam = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const rings = useRef<Record<string, Animation | undefined>>({});
  const btn = useRef<Record<string, HTMLButtonElement | null>>({});
  const mounted = useRef(performance.now());
  useParticles(canvas, prefs.particles && animate && phase !== "INTRO", prefs.quality, sel ?? hover);

  useEffect(() => {
    document.documentElement.classList.add("nc-doc");
    return () => document.documentElement.classList.remove("nc-doc");
  }, []);
  const clearTimers = () => { timers.current.forEach((t) => clearTimeout(t)); timers.current = []; };
  useEffect(() => () => clearTimers(), []);

  // intro (after JOIN THE CULT): neural flight -> city; played once (the URL loses ?intro=1), Esc / click skips
  useEffect(() => {
    if (route.params.get("intro") === "1") navigate("menu", { replace: true });
    if (phase !== "INTRO") return;
    const t = window.setTimeout(() => setPhase("IDLE"), prefs.quality === "balanced" ? 1700 : 2600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // RETURN: back from a tower -> reverse portal on that tower, focus restored
  useEffect(() => {
    let last: string | null = null;
    try { last = sessionStorage.getItem(LAST_KEY); sessionStorage.removeItem(LAST_KEY); } catch { /* storage unavailable */ }
    const t = TOWERS.find((x) => x.key === last);
    if (!t || phase === "INTRO") return;
    setSel(t);
    setPhase("RETURN");
    const id = window.setTimeout(() => { setPhase("IDLE"); setSel(null); btn.current[t.key]?.focus({ preventScroll: true }); }, animate ? 650 : 0);
    timers.current.push(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // independent rotation of every hologram ring (WAAPI: hover slows it down, select stops it)
  useEffect(() => {
    TOWERS.forEach((t, i) => {
      const el = stage.current?.querySelector<HTMLElement>(`[data-ring="${t.key}"] .nc-ring-spin`);
      if (!el || rings.current[t.key]) return;
      const dir = i % 2 ? -1 : 1;
      rings.current[t.key] = el.animate([{ transform: "rotate(0deg)" }, { transform: `rotate(${360 * dir}deg)` }],
                                        { duration: 9000 + i * 1700, iterations: Infinity });
    });
    return () => { Object.values(rings.current).forEach((a) => a?.cancel()); rings.current = {}; };
  }, []);
  useEffect(() => {
    TOWERS.forEach((t) => {
      const a = rings.current[t.key];
      if (!a) return;
      const stopped = !animate || (sel?.key === t.key && phase !== "SELECTED" && phase !== "IDLE") || phase === "INTRO";
      if (stopped) { a.pause(); return; }
      if (a.playState !== "running") a.play();
      a.playbackRate = hover?.key === t.key ? 0.25 : sel && sel.key !== t.key ? 0.5 : prefs.quality === "balanced" ? 0.7 : 1;
    });
  }, [hover, sel, phase, animate, prefs.quality]);

  const cancel = useCallback(() => {
    clearTimers();
    busy.current = false;
    const t = sel;
    setPhase("IDLE");
    setSel(null);
    if (t) btn.current[t.key]?.focus({ preventScroll: true });
  }, [sel]);

  const go = useCallback((t: Tower) => {
    try { sessionStorage.setItem(LAST_KEY, t.key); } catch { /* storage unavailable */ }
    try {
      navigate(t.page);
    } catch (e) {                                                     // navigation failed: never leave the menu half-way
      busy.current = false;
      setPhase("IDLE");
      setToast(`Nie udało się otworzyć ${t.name}: ${String(e)}`);
    }
  }, []);

  /** THE controller: top navigation, tower geometry and keyboard all call this. */
  const select = useCallback((t: Tower) => {
    if (busy.current || phase === "INTRO" || performance.now() - mounted.current < 250) return;   // debounce double click
    busy.current = true;
    setSel(t);
    const k = SCALE[prefs.quality];
    if (!animate || !k) { setPhase("NAVIGATE"); go(t); return; }
    clearTimers();
    for (const [p, at] of SEQ) {
      timers.current.push(window.setTimeout(() => { setPhase(p); if (p === "NAVIGATE") go(t); }, at * k));
    }
  }, [phase, animate, prefs.quality, go]);

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (panel) { setPanel(null); return; }
      if (phase === "INTRO") { setPhase("IDLE"); return; }
      if (phase !== "IDLE" && phase !== "RETURN") cancel();
    };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [phase, panel, cancel]);

  // camera parallax (stage moves slightly against the pointer; disabled by setting / reduced motion / pause)
  useEffect(() => {
    const el = stage.current;
    if (!el || !prefs.parallax || !animate) { cam.current?.style.setProperty("--px", "0"); cam.current?.style.setProperty("--py", "0"); return; }
    const mv = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      cam.current?.style.setProperty("--px", (((e.clientX - r.left) / r.width) - 0.5).toFixed(3));
      cam.current?.style.setProperty("--py", (((e.clientY - r.top) / r.height) - 0.5).toFixed(3));
    };
    el.addEventListener("pointermove", mv);
    return () => el.removeEventListener("pointermove", mv);
  }, [prefs.parallax, animate]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  const fullscreen = () => {
    const d = document as any;
    (d.fullscreenElement ? d.exitFullscreen?.() : document.documentElement.requestFullscreen?.())?.catch?.(() => setToast("Pełny ekran niedostępny w tym oknie"));
  };
  const active = sel ?? hover;
  const camStyle: CSSProperties | undefined = sel && (phase === "PORTAL" || phase === "NAVIGATE")
    ? { transformOrigin: `${pct(sel.ring[0], SCENE_W)} ${pct(sel.ring[1], SCENE_H)}` } : undefined;
  const reach = sel && ["PEPE_REACH", "CONTACT", "PORTAL", "NAVIGATE"].includes(phase);
  const path = sel ? `M ${HANDS[0]} ${HANDS[1]} Q ${(HANDS[0] + sel.ring[0]) / 2} ${Math.min(HANDS[1], sel.ring[1]) + 40} ${sel.ring[0]} ${sel.ring[1] - 70}` : "";

  return (
    <div className={cls("nc", `q-${prefs.quality}`, !animate && "still", paused && "paused")} data-testid="page-menu" data-phase={phase}
      data-selected={sel?.key ?? ""} data-motion={reduced ? "reduced" : paused ? "paused" : prefs.quality}>
      <div className="nc-fill" aria-hidden="true" style={{ backgroundImage: `url(${ASSET}neural-city-scene-blur.webp)` }} />
      <div className="nc-stage" ref={stage} data-testid="nc-stage">
        <div className={cls("nc-cam", phase === "PORTAL" || phase === "NAVIGATE" ? "fly" : "", phase === "RETURN" && "back")} ref={cam} style={camStyle}>
          <img className="nc-scene" src={`${ASSET}neural-city-scene.webp`} draggable={false}
            alt="Pepe zbudowany ze świetlistej sieci neuronowej przy holograficznym stole z siedmioma wieżami PepeMarketWizard" />
          <canvas className="nc-fx" ref={canvas} aria-hidden="true" />
          <div className="nc-aura" aria-hidden="true" />
          <div className={cls("nc-core", active && "hot")} aria-hidden="true" style={{ left: pct(CORE[0], SCENE_W), top: pct(CORE[1], SCENE_H) }}><i /><i /><i /></div>
          {TOWERS.map((t) => (
            <div key={t.key} className={cls("nc-ring", hover?.key === t.key && "hover", sel?.key === t.key && "sel", sel?.key === t.key && phase === "CONTACT" && "contact")}
              data-ring={t.key} aria-hidden="true" style={{ left: pct(t.ring[0], SCENE_W), top: pct(t.ring[1], SCENE_H), width: pct(t.ring[2] * 2, SCENE_W), "--c": t.color } as CSSProperties}>
              <div className="nc-ring-tilt"><div className="nc-ring-spin" /></div>
            </div>))}
          <svg className={cls("nc-reach", reach && "on")} viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} preserveAspectRatio="none" aria-hidden="true">
            {sel && <path d={path} pathLength={1} />}
          </svg>
          {sel && (phase === "PORTAL" || phase === "NAVIGATE" || phase === "RETURN") &&
            <div className={cls("nc-portal", phase === "RETURN" && "rev")} aria-hidden="true" style={{ left: pct(sel.ring[0], SCENE_W), top: pct(sel.ring[1] - 60, SCENE_H) }}><i /><i /><i /></div>}
          {TOWERS.map((t) => (
            <span key={t.key} className={cls("nc-plate", active?.key === t.key && "on")} style={boxStyle(t.plate)} data-plate={t.key} aria-hidden="true">
              <b>{t.name}</b></span>))}
          <div className="nc-towers" role="group" aria-label="Wieże Neural City – wybierz moduł">
            {TOWERS.map((t) => (
              <button key={t.key} type="button" ref={(el) => { btn.current[t.key] = el; }} className={cls("nc-hit", hover?.key === t.key && "hover", sel?.key === t.key && "sel")}
                style={boxStyle(t.hit)} data-testid={`nc-tower-${t.key}`} data-page={t.page} aria-label={`${t.name} – ${t.panel}. ${t.desc}`}
                title={`${t.name}${t.legacy.length ? ` (dawniej ${t.legacy.join(" / ")})` : ""} → ${t.panel}`}
                onMouseEnter={() => setHover(t)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(t)} onBlur={() => setHover(null)}
                onClick={() => select(t)} />))}
          </div>
        </div>

        <header className="nc-top">
          <nav className="nc-nav" aria-label="Nawigacja główna PepeMarketWizard">
            <button type="button" className="nc-pill home on" aria-current="page" data-testid="nc-nav-home" title="Menu główne">⌂ HOME</button>
            {TOWERS.map((t) => (
              <button key={t.key} type="button" className={cls("nc-pill", sel?.key === t.key && "sel")} data-testid={`nc-nav-${t.key}`} data-page={t.page}
                onClick={() => select(t)} onMouseEnter={() => setHover(t)} onMouseLeave={() => setHover(null)} title={`${t.name} → ${t.panel}`}>
                {t.key === "news" ? "NEWS" : t.name}</button>))}
          </nav>
        </header>
        <section className="nc-hud" aria-label="Account overview – dane z rachunku MT5 bota" data-testid="nc-hud">
          <div className="nc-hud-h">ACCOUNT OVERVIEW</div>
          <div className="nc-hud-g">
            {hud.map((x) => (
              <div key={x.key} data-testid={`nc-stat-${x.key}`} data-kind={x.kind}>
                <span>{x.label}</span><strong>{x.value}</strong><small>{x.sub}</small><Tag kind={x.kind} /></div>))}
          </div>
        </section>
        <aside className="nc-quote" aria-label="They call us cult but we are something more">
          <span>They call us cult</span><span className="hl">but we are something more</span></aside>
        <div className="nc-tag" data-testid="nc-tag"><i />NEURAL CITY V7.0 · 2.5D <em>· {reduced ? "REDUCED MOTION" : paused ? "PAUZA" : prefs.quality.toUpperCase()}</em></div>
        <div className="nc-tip" role="status" aria-live="polite" data-testid="nc-tip">
          {sel && phase !== "IDLE" && phase !== "RETURN" ? `Otwieranie ${sel.name}… (Esc – anuluj)` : active ? `${active.name} – ${active.desc}` : "Wybierz wieżę, aby przejść do sekcji"}</div>
        <div className="nc-tools" role="toolbar" aria-label="Animacja menu">
          <button type="button" className="nc-tool" onClick={() => setPaused(!paused)} aria-pressed={paused} data-testid="nc-pause"
            aria-label={paused ? "Wznów animacje" : "Wstrzymaj animacje"} title={paused ? "Wznów animacje" : "Wstrzymaj animacje"}>{paused ? "▶" : "Ⅱ"}</button>
          <button type="button" className="nc-tool" onClick={fullscreen} aria-label="Pełny ekran" title="Pełny ekran">⛶</button>
          <button type="button" className="nc-tool" onClick={() => setPanel(panel === "settings" ? null : "settings")} aria-expanded={panel === "settings"}
            aria-label="Ustawienia animacji" title="Ustawienia animacji" data-testid="nc-settings">⚙</button>
          <button type="button" className="nc-tool" onClick={() => setPanel(panel === "info" ? null : "info")} aria-expanded={panel === "info"}
            aria-label="Informacje o menu" title="Informacje" data-testid="nc-info">ⓘ</button>
        </div>
        {phase === "INTRO" && (
          <div className="nc-intro" data-testid="nc-intro" onClick={() => setPhase("IDLE")} role="presentation">
            <img src={`${ASSET}neuron-flight.webp`} alt="" aria-hidden="true" />
            <div className="nc-intro-t"><small>PEPEMARKETWIZARD</small><b>NEURAL CITY</b><em>INITIALIZING HOLOGRAPHIC INTERFACE</em></div>
            <button type="button" className="nc-skip" onClick={() => setPhase("IDLE")} data-testid="nc-skip">Pomiń intro ›</button>
          </div>)}
      </div>

      <nav className="nc-list" aria-label="Wieże (lista)">
        {TOWERS.map((t) => <button key={t.key} type="button" onClick={() => select(t)} data-testid={`nc-list-${t.key}`}>{t.name}<small>{t.panel}</small></button>)}
      </nav>

      {panel === "settings" && (
        <section className="nc-panel" role="dialog" aria-modal="false" aria-label="Ustawienia animacji" data-testid="nc-settings-panel">
          <header><b>NEURAL ANIMATION ENGINE</b><button type="button" onClick={() => setPanel(null)} aria-label="Zamknij">×</button></header>
          <div className="nc-q" role="group" aria-label="Jakość animacji">
            {(["cinematic", "balanced", "performance"] as Quality[]).map((q) => (
              <button key={q} type="button" aria-pressed={prefs.quality === q} onClick={() => setPrefs({ ...prefs, quality: q })} data-quality={q}>{q.toUpperCase()}</button>))}
          </div>
          <label><input type="checkbox" checked={prefs.parallax} onChange={(e) => setPrefs({ ...prefs, parallax: e.target.checked })} /> Paralaksa kamery</label>
          <label><input type="checkbox" checked={prefs.particles} onChange={(e) => setPrefs({ ...prefs, particles: e.target.checked })} /> Cząsteczki neuronowe</label>
          <label><input type="checkbox" checked={prefs.intro} onChange={(e) => setPrefs({ ...prefs, intro: e.target.checked })} /> Animacja wejścia po JOIN THE CULT</label>
          <button type="button" className="nc-replay" onClick={() => { setPanel(null); if (!reduced) setPhase("INTRO"); window.setTimeout(() => setPhase("IDLE"), 2600); }}>
            ↻ Odtwórz animację wejścia</button>
          <p>{reduced ? "System prosi o ograniczony ruch – sekwencje i intro są wyłączone." : "PERFORMANCE: bez sekwencji i cząsteczek, wieże otwierają się od razu."}</p>
        </section>)}
      {panel === "info" && (
        <section className="nc-panel wide" role="dialog" aria-modal="false" aria-label="Informacje o menu" data-testid="nc-info-panel">
          <header><b>NEURAL CITY V7.0 – TRYB 2.5D</b><button type="button" onClick={() => setPanel(null)} aria-label="Zamknij">×</button></header>
          <p>Scena to zatwierdzona grafika (wieże i Pepe są obrazem, nie modelem 3D). Animowane są pierścienie hologramów, cząsteczki,
            prąd na stole, rdzeń, świetlna ścieżka gestu Pepe (efekt stylizowany 2.5D), portal i przelot kamery. Brakujące zasoby pełnego 3D:
            modele glTF siedmiu wież, model Pepe z rigiem i IK dłoni, model stołu i rdzenia.</p>
          <p>Winratio, ROI i Equity pochodzą z istniejącej warstwy statystyk bota (znacznik źródła przy każdej wartości); bez danych – N/A.
            Menu tylko nawiguje do istniejących paneli i nie wykonuje żadnych operacji handlowych.</p>
          <ul>{TOWERS.map((t) => <li key={t.key}><b>{t.name}</b>{t.legacy.length ? ` (dawniej ${t.legacy.join(" / ")})` : ""} → {t.panel} <code>#/{t.page}</code>, alias <code>#/{t.alias}</code></li>)}</ul>
        </section>)}
      {toast && <div className="nc-toast" role="alert">{toast}</div>}
    </div>);
}
