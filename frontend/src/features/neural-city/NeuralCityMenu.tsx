// MAIN MENU V2 – Neural Table (PepeMarketWizard_Menu_New_V2). Three Pepe in dark suits at the round neural table with EIGHT towers.
// The screen is ONLY the menu: no information panels, no charts / portfolio cards, no bottom launcher buttons. A small logo top-left
// and the top navigation with all eight modules; every tower is its own focusable button. Towers and the top navigation call ONE
// controller and open the same EXISTING panel of the bot (towers.ts). The menu fetches no MT5 data and shows no statistics.
//
// HONEST SCOPE: 2.5D – the towers and the three Pepe are pixels of the approved artwork, NOT 3D models (no glTF towers, no rigged Pepe).
// Animated live on top of it: neural filaments from the brain core to every tower with travelling impulses, the core pulse, a neural
// wave, hologram rings at the base of each tower (independent speeds, slower on hover, stopped on select), light impulses on the Pepe,
// floating banknotes, a light path from the hands of the Pepe in the middle to the selected tower, the portal and a camera fly-in.
//
// Controller: IDLE -> SELECTED -> STOP_ROTATION -> PEPE_REACH -> CONTACT -> PORTAL -> NAVIGATE (-> RETURN when the menu is opened again).
// Double click is debounced, Esc cancels, the selected tower gets the focus back after returning. Reduced motion / pause / Performance:
// no sequence, direct navigation. The render loop stops when the menu is unmounted, hidden or paused.
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { navigate, type Route } from "../../router";
import { cls } from "../../util";
import StudioButton from "../pmw133/StudioButton";
import { CORE, HANDS, PEPES, SCENE_H, SCENE_W, TOWERS, boxStyle, pct, type Tower } from "./towers";
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

/** Point on the neural filament core -> tower (quadratic curve bowed upwards), t in 0..1, scene pixels. */
function bez(b: [number, number], t: number): [number, number] {
  const mx = (CORE[0] + b[0]) / 2, my = (CORE[1] + b[1]) / 2 - 55, v = 1 - t;
  return [v * v * CORE[0] + 2 * v * t * mx + t * t * b[0], v * v * CORE[1] + 2 * v * t * my + t * t * b[1]];
}

/** Neural filaments, travelling impulses, core pulse and neural wave (canvas in scene coordinates; stopped when off / hidden). */
function useNeuralTable(ref: React.RefObject<HTMLCanvasElement | null>, on: boolean, quality: Quality, target: Tower | null, wave: number) {
  const tgt = useRef<Tower | null>(null);
  tgt.current = target;
  const waveAt = useRef(-1e9);
  useEffect(() => { if (wave) waveAt.current = performance.now(); }, [wave]);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    let raf = 0, k = 1;
    const size = () => {
      const r = c.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, quality === "cinematic" ? 2 : 1);
      c.width = Math.max(1, Math.round(r.width * dpr)); c.height = Math.max(1, Math.round(r.height * dpr));
      k = c.width / SCENE_W;
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(c);
    const strands = quality === "cinematic" ? [-1, 0, 1] : [0];
    // the filaments are painted ONCE into an offscreen buffer (again only on resize / when the highlighted tower changes);
    // every frame only copies the buffer and draws the impulses -> the main thread stays free for the navigation sequence
    const buf = document.createElement("canvas");
    let bufKey = "\u0000";
    const paintStatic = (hotKey: string | null) => {
      buf.width = c.width; buf.height = c.height;
      const b = buf.getContext("2d");
      if (!b) return;
      b.setTransform(k, 0, 0, k, 0, 0);
      b.globalCompositeOperation = "lighter";
      TOWERS.forEach((t) => {
        const hot = hotKey === t.key;
        const a = hot ? 0.75 : 0.26;
        for (const s of strands) {
          b.beginPath();
          for (let n = 0; n <= 28; n++) {
            const u = n / 28, p = bez(t.base, u);
            const y = p[1] + Math.sin(u * Math.PI) * s * 13;
            n ? b.lineTo(p[0], y) : b.moveTo(p[0], y);
          }
          b.strokeStyle = s === 0 ? `rgba(64,233,255,${a})` : `rgba(255,179,95,${a * 0.4})`;
          b.lineWidth = s === 0 ? (hot ? 3 : 1.4) : 0.7;
          b.shadowColor = s === 0 ? "#37eafe" : "#ffd05f";
          b.shadowBlur = hot ? 18 : 8;
          b.stroke();
        }
      });
      bufKey = `${hotKey}|${c.width}x${c.height}`;
    };
    const draw = (now: number, still: boolean) => {
      const hotKey = tgt.current?.key ?? null;
      if (bufKey !== `${hotKey}|${c.width}x${c.height}`) paintStatic(hotKey);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, c.width, c.height);
      ctx.drawImage(buf, 0, 0);
      ctx.setTransform(k, 0, 0, k, 0, 0);
      ctx.globalCompositeOperation = "lighter";
      const clock = still ? 0 : now / 1000;
      if (!still) TOWERS.forEach((t, i) => {
        const hot = hotKey === t.key;
        for (let j = 0; j < 3; j++) {                                 // impulses travelling core -> tower (halo + dot, no shadow blur)
          const u = (clock * (0.23 + 0.035 * i) + j / 3 + i * 0.11) % 1, p = bez(t.base, u);
          const r = hot ? 4.8 : 2.6;
          ctx.globalAlpha = 0.28; ctx.fillStyle = t.color;
          ctx.beginPath(); ctx.arc(p[0], p[1], r * 2.6, 0, Math.PI * 2); ctx.fill();
          ctx.globalAlpha = 1; ctx.fillStyle = j === 0 ? t.color : "#b8faff";
          ctx.beginPath(); ctx.arc(p[0], p[1], r, 0, Math.PI * 2); ctx.fill();
        }
      });
      const f = still ? 0.5 : 0.5 + 0.5 * Math.sin(clock * 3);         // core pulse
      ctx.beginPath(); ctx.arc(CORE[0], CORE[1], 21 + 14 * f, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(83,255,255,${0.18 + 0.22 * f})`; ctx.lineWidth = 2; ctx.stroke();
      const age = (now - waveAt.current) / 1100;                     // neural wave (Pepe in the middle / tower activation)
      if (!still && age >= 0 && age < 1) {
        ctx.beginPath(); ctx.ellipse(CORE[0], CORE[1], 30 + 290 * age, 12 + 115 * age, 0, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(151,255,240,${(1 - age) * 0.65})`; ctx.lineWidth = (1 - age) * 5; ctx.stroke();
      }
      ctx.globalCompositeOperation = "source-over";
    };
    const frame = (now: number) => {
      if (!document.hidden) draw(now, false);
      raf = requestAnimationFrame(frame);
    };
    if (on && quality !== "performance") raf = requestAnimationFrame(frame);
    else draw(0, true);                                              // static filaments (paused / reduced motion / Performance)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, c.width, c.height); };
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
  const [wave, setWave] = useState(0);
  const [flash, setFlash] = useState<Record<string, number>>({});
  const timers = useRef<number[]>([]);
  const busy = useRef(false);
  const stage = useRef<HTMLDivElement>(null);
  const cam = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const rings = useRef<Record<string, Animation | undefined>>({});
  const btn = useRef<Record<string, HTMLButtonElement | null>>({});
  const mounted = useRef(performance.now());
  useNeuralTable(canvas, prefs.particles && animate && phase !== "INTRO", prefs.quality, sel ?? hover, wave);

  useEffect(() => {
    document.documentElement.classList.add("nc-doc");
    return () => document.documentElement.classList.remove("nc-doc");
  }, []);
  const clearTimers = () => { timers.current.forEach((t) => clearTimeout(t)); timers.current = []; };
  useEffect(() => () => clearTimers(), []);

  // intro (after JOIN THE CULT): neural flight -> table; played once (the URL loses ?intro=1), Esc / click skips
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
                                        { duration: 9000 + i * 1300, iterations: Infinity });
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

  /** THE controller: top navigation, tower geometry, the list and the keyboard all call this. */
  const select = useCallback((t: Tower) => {
    if (busy.current || phase === "INTRO" || performance.now() - mounted.current < 250) return;   // debounce double click
    busy.current = true;
    setSel(t);
    setWave((n) => n + 1);
    const k = SCALE[prefs.quality];
    if (!animate || !k) { setPhase("NAVIGATE"); go(t); return; }
    clearTimers();
    for (const [p, at] of SEQ) {
      timers.current.push(window.setTimeout(() => {
        setPhase(p);
        if (p === "NAVIGATE") timers.current.push(window.setTimeout(() => go(t), 60));   // NAVIGATE is rendered (portal flash), then the panel opens
      }, at * k));
    }
  }, [phase, animate, prefs.quality, go]);

  const poke = (key: string) => {                                    // click on a Pepe: light impulse (+ neural wave for the middle one)
    setFlash((f) => ({ ...f, [key]: (f[key] || 0) + 1 }));
    if (key === "center") setWave((n) => n + 1);
  };

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

  const active = sel ?? hover;
  const camStyle: CSSProperties | undefined = sel && (phase === "PORTAL" || phase === "NAVIGATE")
    ? { transformOrigin: `${pct(sel.base[0], SCENE_W)} ${pct(sel.base[1] - 90, SCENE_H)}` } : undefined;
  const reach = sel && ["PEPE_REACH", "CONTACT", "PORTAL", "NAVIGATE"].includes(phase);
  const path = sel ? `M ${HANDS[0]} ${HANDS[1]} Q ${(HANDS[0] + sel.base[0]) / 2} ${Math.min(HANDS[1], sel.base[1]) + 30} ${sel.base[0]} ${sel.base[1] - 110}` : "";

  return (
    <div className={cls("nc", `q-${prefs.quality}`, !animate && "still", paused && "paused")} data-testid="page-menu" data-phase={phase}
      data-selected={sel?.key ?? ""} data-motion={reduced ? "reduced" : paused ? "paused" : prefs.quality}>
      <div className="nc-fill" aria-hidden="true" style={{ backgroundImage: `url(${ASSET}neural-table-scene-blur.webp)` }} />
      <div className="nc-stage" ref={stage} data-testid="nc-stage">
        <div className={cls("nc-cam", phase === "PORTAL" || phase === "NAVIGATE" ? "fly" : "", phase === "RETURN" && "back")} ref={cam} style={camStyle}>
          <img className="nc-scene" src={`${ASSET}neural-table-scene.webp`} draggable={false}
            alt="Trzech Pepe w ciemnych garniturach przy okrągłym neonowym stole z sieci neuronowych z ośmioma wieżami PepeMarketWizard" />
          <canvas className="nc-fx" ref={canvas} aria-hidden="true" />
          <div className={cls("nc-core", active && "hot")} aria-hidden="true" style={{ left: pct(CORE[0], SCENE_W), top: pct(CORE[1], SCENE_H) }}><i /><i /><i /></div>
          {TOWERS.map((t) => (
            <div key={t.key} className={cls("nc-ring", hover?.key === t.key && "hover", sel?.key === t.key && "sel", sel?.key === t.key && phase === "CONTACT" && "contact")}
              data-ring={t.key} aria-hidden="true"
              style={{ left: pct(t.base[0], SCENE_W), top: pct(t.base[1] - 18, SCENE_H), width: pct(190, SCENE_W), "--c": t.color } as CSSProperties}>
              <div className="nc-ring-tilt"><div className="nc-ring-spin" /></div>
            </div>))}
          {PEPES.map((p) => (
            <span key={`${p.key}-${flash[p.key] || 0}`} className={cls("nc-flash", !!flash[p.key] && "on")} aria-hidden="true"
              style={{ left: pct(p.flash[0], SCENE_W), top: pct(p.flash[1], SCENE_H) }} />))}
          <div className="nc-cash" aria-hidden="true"><i /><i /><i /></div>
          <svg className={cls("nc-reach", reach && "on")} viewBox={`0 0 ${SCENE_W} ${SCENE_H}`} preserveAspectRatio="none" aria-hidden="true">
            {sel && <path d={path} pathLength={1} style={{ "--c": sel.color } as CSSProperties} />}
          </svg>
          {sel && (phase === "PORTAL" || phase === "NAVIGATE" || phase === "RETURN") &&
            <div className={cls("nc-portal", phase === "RETURN" && "rev")} aria-hidden="true"
              style={{ left: pct(sel.base[0], SCENE_W), top: pct(sel.base[1] - 90, SCENE_H), "--c": sel.color } as CSSProperties}><i /><i /><i /></div>}
          {TOWERS.map((t) => (
            <span key={t.key} className={cls("nc-plate", active?.key === t.key && "on")} style={{ ...boxStyle(t.plate), "--c": t.color } as CSSProperties}
              data-plate={t.key} aria-hidden="true"><b>{t.name}</b></span>))}
          <div className="nc-pepes">
            {PEPES.map((p) => (
              <button key={p.key} type="button" className="nc-pepe" style={boxStyle(p.hit)} data-testid={`nc-pepe-${p.key}`} aria-label={p.label}
                title={p.label} onClick={() => poke(p.key)} />))}
          </div>
          <div className="nc-towers" role="group" aria-label="Wieże stołu neuronowego – wybierz moduł">
            {TOWERS.map((t) => (
              <button key={t.key} type="button" ref={(el) => { btn.current[t.key] = el; }} className={cls("nc-hit", hover?.key === t.key && "hover", sel?.key === t.key && "sel")}
                style={{ ...boxStyle(t.hit), "--c": t.color } as CSSProperties} data-testid={`nc-tower-${t.key}`} data-page={t.page} data-id={t.id}
                aria-label={`${t.name} – ${t.panel}. ${t.desc}`}
                title={`${t.name}${t.legacy.length ? ` (dawniej ${t.legacy[0]})` : ""} → ${t.panel}`}
                onMouseEnter={() => setHover(t)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(t)} onBlur={() => setHover(null)}
                onClick={() => select(t)}><span className="nc-hit-name" aria-hidden="true">{t.name}</span></button>))}
          </div>
        </div>

        <header className="nc-top">
          <a className="nc-logo" href="#/menu" aria-label="PepeMarketWizard – menu główne" data-testid="nc-logo" onClick={(e) => e.preventDefault()}>
            <span className="nc-logo-mark" aria-hidden="true">♛</span>Pepe<span className="m">Market</span><span className="w">Wizard</span></a>
          <nav className="nc-nav" aria-label="Nawigacja główna PepeMarketWizard">
            {TOWERS.map((t) => (
              <button key={t.key} type="button" className={cls("nc-pill", sel?.key === t.key && "sel", hover?.key === t.key && "hov")} data-testid={`nc-nav-${t.key}`}
                data-page={t.page} data-id={t.id} style={{ "--c": t.color } as CSSProperties}
                onClick={() => select(t)} onMouseEnter={() => setHover(t)} onMouseLeave={() => setHover(null)} title={`${t.name} → ${t.panel}`}>
                {t.name}</button>))}
          </nav>
          <div className="nc-tools" role="toolbar" aria-label="Narzędzia menu">
            <StudioButton variant="plain" className="nc-tool nc-tool-wide" />
            <button type="button" className="nc-tool" onClick={() => setPaused(!paused)} aria-pressed={paused} data-testid="nc-pause"
              aria-label={paused ? "Wznów animacje" : "Wstrzymaj animacje"} title={paused ? "Wznów animacje" : "Wstrzymaj animacje"}>{paused ? "▶" : "Ⅱ"}</button>
            <button type="button" className="nc-tool" onClick={() => setPanel(panel === "settings" ? null : "settings")} aria-expanded={panel === "settings"}
              aria-label="Ustawienia animacji" title="Ustawienia animacji" data-testid="nc-settings">✧</button>
            <button type="button" className="nc-tool" onClick={() => setPanel(panel === "info" ? null : "info")} aria-expanded={panel === "info"}
              aria-label="Informacje o menu" title="Informacje" data-testid="nc-info">ⓘ</button>
          </div>
        </header>
        <div className="nc-tip" role="status" aria-live="polite" data-testid="nc-tip">
          {sel && phase !== "IDLE" && phase !== "RETURN" ? `Otwieranie ${sel.name}… (Esc – anuluj)` : active ? `${active.name} – ${active.desc}` : "WYBIERZ WIEŻĘ LUB SEKCJĘ W GÓRNYM MENU"}</div>
        <div className="nc-tag" data-testid="nc-tag"><i />NEURAL TABLE · 2.5D <em>· {reduced ? "REDUCED MOTION" : paused ? "PAUZA" : prefs.quality.toUpperCase()}</em></div>
        {phase === "INTRO" && (
          <div className="nc-intro" data-testid="nc-intro" onClick={() => setPhase("IDLE")} role="presentation">
            <img src={`${ASSET}neuron-flight.webp`} alt="" aria-hidden="true" />
            <div className="nc-intro-t"><small>PEPEMARKETWIZARD</small><b>NEURAL TABLE</b><em>INITIALIZING HOLOGRAPHIC INTERFACE</em></div>
            <button type="button" className="nc-skip" onClick={() => setPhase("IDLE")} data-testid="nc-skip">Pomiń intro ›</button>
          </div>)}
      </div>

      <nav className="nc-list" aria-label="Wieże (lista)">
        {TOWERS.map((t) => <button key={t.key} type="button" onClick={() => select(t)} data-testid={`nc-list-${t.key}`} style={{ "--c": t.color } as CSSProperties}>
          <span aria-hidden="true">{t.icon}</span> {t.name}<small>{t.panel}</small></button>)}
      </nav>

      {panel === "settings" && (
        <section className="nc-panel" role="dialog" aria-modal="false" aria-label="Ustawienia animacji" data-testid="nc-settings-panel">
          <header><b>NEURAL ANIMATION ENGINE</b><button type="button" onClick={() => setPanel(null)} aria-label="Zamknij">×</button></header>
          <div className="nc-q" role="group" aria-label="Jakość animacji">
            {(["cinematic", "balanced", "performance"] as Quality[]).map((q) => (
              <button key={q} type="button" aria-pressed={prefs.quality === q} onClick={() => setPrefs({ ...prefs, quality: q })} data-quality={q}>{q.toUpperCase()}</button>))}
          </div>
          <label><input type="checkbox" checked={prefs.parallax} onChange={(e) => setPrefs({ ...prefs, parallax: e.target.checked })} /> Paralaksa kamery</label>
          <label><input type="checkbox" checked={prefs.particles} onChange={(e) => setPrefs({ ...prefs, particles: e.target.checked })} /> Impulsy na ścieżkach neuronowych</label>
          <label><input type="checkbox" checked={prefs.intro} onChange={(e) => setPrefs({ ...prefs, intro: e.target.checked })} /> Animacja wejścia po JOIN THE CULT</label>
          <button type="button" className="nc-replay" onClick={() => { setPanel(null); if (!reduced) setPhase("INTRO"); window.setTimeout(() => setPhase("IDLE"), 2600); }}>
            ↻ Odtwórz animację wejścia</button>
          <p>{reduced ? "System prosi o ograniczony ruch – sekwencje i intro są wyłączone." : "PERFORMANCE: bez sekwencji i impulsów, wieże otwierają się od razu."}</p>
        </section>)}
      {panel === "info" && (
        <section className="nc-panel wide" role="dialog" aria-modal="false" aria-label="Informacje o menu" data-testid="nc-info-panel">
          <header><b>MAIN MENU V2 – NEURAL TABLE (2.5D)</b><button type="button" onClick={() => setPanel(null)} aria-label="Zamknij">×</button></header>
          <p>Scena to zatwierdzona grafika: wieże i trzech Pepe są obrazem, nie modelami 3D. Animowane są ścieżki neuronowe z impulsami, rdzeń,
            fala neuronowa, pierścienie hologramów u podstaw wież, impulsy świetlne Pepe, banknoty, świetlna ścieżka do wybranej wieży, portal
            i przelot kamery. Brakujące zasoby pełnego 3D: modele glTF ośmiu wież, modele Pepe z rigiem (ręce, liczenie banknotów), model stołu.</p>
          <p>Menu tylko nawiguje do istniejących paneli bota – nie pobiera danych MT5, nie pokazuje statystyk i nie wykonuje operacji handlowych.</p>
          <ul>{TOWERS.map((t) => <li key={t.key}><b>{t.name}</b> ({t.id}) → {t.panel} <code>#/{t.page}</code>{t.legacy.length ? `, dawniej ${t.legacy.join(" / ")}` : ""}</li>)}</ul>
        </section>)}
      {toast && <div className="nc-toast" role="alert">{toast}</div>}
    </div>);
}
