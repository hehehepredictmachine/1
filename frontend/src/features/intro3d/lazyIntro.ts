// Intro 3D w menu głównym (I2 / I3): obiekt z kontraktem <video> (play, pause, currentTime, duration, muted, readyState, style, 'ended' /
// 'error'), z którego korzysta silnik menu dokładnie jak REF_C (`video = new PMW_Intro3D(canvas)`). Różnice integracyjne (bez zmian wyglądu):
//  * scena (three.js, bryła postaci) ładuje się leniwie przy pierwszym odtworzeniu / przewinięciu – gdy intro jest pomijane, nic nie jest
//    pobierane ani tworzone;
//  * release(): po wejściu do menu zasoby sceny (geometrie, tekstury, render targety) są zwalniane, kontekst WebGL płótna zostaje – powtórka
//    („Odtwórz intro”, R) buduje scenę od nowa na tym samym płótnie; dispose(): także kontekst (odmontowanie menu);
//  * poziom jakości (I3): PEŁNY / ŚREDNI / NISKI wybierany w pierwszych 1,5 s (scena jest wtedy w czerni) i zapamiętany w
//    localStorage "pmw.intro.quality"; tryb testowy zawsze PEŁNY.
const INTRO_DURATION = 13.8;                // = TL.duration (sprawdza test jednostkowy) – bez statycznego importu sceny

export type IntroQuality = "FULL" | "MEDIUM" | "LOW";
const QKEY = "pmw.intro.quality";
const Q_OPTS: Record<IntroQuality, { pixelRatioCap: number; reflections: boolean; shadows: boolean }> = {
  FULL: { pixelRatioCap: 1.65, reflections: true, shadows: true },
  MEDIUM: { pixelRatioCap: 1.25, reflections: false, shadows: true },
  LOW: { pixelRatioCap: 1.0, reflections: false, shadows: false },
};
function readQ(): IntroQuality { try { const v = localStorage.getItem(QKEY); return v === "MEDIUM" || v === "LOW" ? v : "FULL"; } catch { return "FULL"; } }
function saveQ(q: IntroQuality) { try { localStorage.setItem(QKEY, q); } catch { /* brak pamięci przeglądarki */ } }

export class LazyIntro extends EventTarget {
  readonly duration = INTRO_DURATION;
  muted = true;                       // intro 3D nie ma dźwięku – właściwość zostaje dla zgodności z <video>
  readyState = 0;
  paused = true;
  quality: IntroQuality;
  private impl: any = null;
  private loading: Promise<void> | null = null;
  private t = 0;
  private probe = { raf: 0, n: 0, sum: 0, last: 0 };
  constructor(private canvas: HTMLCanvasElement, private opts: { forceFull?: boolean } = {}) {
    super();
    this.quality = opts.forceFull ? "FULL" : readQ();
  }
  get style(): CSSStyleDeclaration { return this.canvas.style; }
  get currentTime(): number { return this.impl ? this.impl.currentTime : this.t; }
  set currentTime(v: number) { this.t = Math.max(0, Math.min(this.duration, v)); if (this.impl) this.impl.currentTime = this.t; }

  private fail(err?: unknown) {
    if (err) console.warn("[intro3d]", err);
    this.paused = true; this.readyState = 0;
    this.dispatchEvent(new Event("error"));
  }
  private build(): void {
    const mod = (this as any).mod;
    const impl = new mod.Intro3D(this.canvas, Q_OPTS[this.quality]);
    impl.addEventListener("ended", () => { this.paused = true; this.t = this.duration; this.dispatchEvent(new Event("ended")); });
    impl.addEventListener("error", () => this.fail());
    impl.currentTime = this.t;
    this.impl = impl; this.readyState = 4;
  }
  private load(): Promise<void> {
    if (this.impl) return Promise.resolve();
    if (!this.loading) {
      this.loading = import("./index").then((mod) => { (this as any).mod = mod; this.build(); })
        .catch((err) => { this.loading = null; this.fail(err); throw err; });
    }
    return this.loading;
  }
  play(): Promise<void> {
    this.paused = false;
    return this.load().then(() => {
      if (this.paused || !this.impl) return;
      if (this.impl.currentTime >= this.duration) this.impl.currentTime = 0;
      this.startProbe();
      return this.impl.play();
    }).catch(() => undefined);
  }
  pause(): void { this.paused = true; this.stopProbe(); this.impl?.pause(); }
  /** Tryb testowy: wstrzymuje i rysuje klatkę t (rozwiązuje po narysowaniu). */
  seek(t: number): Promise<void> {
    this.paused = true; this.stopProbe(); this.t = t;
    return this.load().then(() => { this.impl.pause(); this.impl.seek(t); });
  }
  /** I3: średni czas klatki w pierwszych 1,5 s odtwarzania (czerń) → niższy poziom jakości, zapamiętany na kolejne starty; po zejściu na
   *  ŚREDNI jeszcze jeden pomiar do 2,5 s (wejście z czerni trwa do 2,4 s) → ewentualnie NISKI. */
  private startProbe(until = 1.5) {
    if (this.opts.forceFull || this.quality === "LOW" || (until === 1.5 && this.impl.currentTime > 0.05)) return;
    const P = this.probe; P.n = 0; P.sum = 0; P.last = performance.now();
    const step = (now: number) => {
      if (this.paused || !this.impl) return;
      P.sum += now - P.last; P.last = now; P.n++;
      if (this.impl.currentTime < until) { P.raf = requestAnimationFrame(step); return; }
      const avg = P.sum / Math.max(1, P.n);
      const next: IntroQuality | null = this.quality === "FULL" && avg > 22 ? "MEDIUM" : this.quality === "MEDIUM" && avg > 28 ? "LOW" : null;
      if (next) { this.quality = next; saveQ(next); this.rebuild(); }
    };
    P.raf = requestAnimationFrame(step);
  }
  private stopProbe() { cancelAnimationFrame(this.probe.raf); this.probe.raf = 0; }
  private rebuild() {
    const t = this.impl.currentTime, playing = !this.paused;
    this.impl.dispose({ keepContext: true }); this.impl = null;
    try { this.t = t; this.build(); } catch (err) { this.fail(err); return; }
    if (playing) { this.impl.play(); if (t < 2.0) this.startProbe(t + 0.5 > 2.5 ? 2.5 : Math.max(t + 0.5, 2.0)); }
  }
  /** Po wejściu do menu: zwolnij scenę (pamięć GPU / RAM), kontekst płótna zostaje na powtórkę. */
  release(): void { this.stopProbe(); if (this.impl) { this.impl.dispose({ keepContext: true }); this.impl = null; this.readyState = 0; } this.loading = null; }
  /** Odmontowanie menu: scena i kontekst WebGL. */
  dispose(): void { this.stopProbe(); this.paused = true; if (this.impl) { this.impl.dispose(); this.impl = null; } this.loading = null; this.readyState = 0; }
}
