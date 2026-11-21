// Trasa #/menu (E1; 1.44.1: intro = film Apollo23_intro_land.mp4 zamiast intro 3D z 1.42.7): intro + menu 3 planet (FOREX / CRYPTO / OTC). Markup i style ze wzorca REF_A, silnik w menuEngine.ts
// montowany w useEffect (jeden kontekst WebGL, dispose przy odmontowaniu). CRYPTO / OTC: ekran „tryb w przygotowaniu” bez żadnego
// wywołania API – wybór planety to nawigacja, nie przełączenie profilu rynku bota (S2 §4).
import { useEffect, useRef } from "react";
import { useStore } from "../../store";
import { mountMenu, PREPARING_NOTE, type MenuElements, type Mode, type Pose } from "./menuEngine";
import { prefersReducedMotion, shouldPlayIntro } from "./introGate";
import introFilm from "../../assets/Apollo23_intro_land.mp4";      // build: dist/assets/Apollo23_intro_land-<hash>.mp4 (serwowane z /assets/)
import "./cinematic.css";

const SOUND_KEY = "pmw.intro.sound";
const soundOn = () => { try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch { return true; } };
const saveSound = (on: boolean) => { try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch { /* bez trwałości */ } };

type Props = {
  onSettings?(): void;                                     // ustawienia otwiera pasek ikon systemowych (SystemIcons)
  onMenuReady?(): void;
  onForexReady?(pose: Pose): void;
  forceSoftware?: boolean;
  testIntro?: boolean;                                     // testy: intro zawsze (bez względu na „raz na sesję”)
};

export default function CinematicMenu({ onMenuReady, onForexReady, forceSoftware, testIntro }: Props) {
  const { s } = useStore();
  const rootRef = useRef<HTMLDivElement>(null);
  const forexRef = useRef(onForexReady);
  forexRef.current = onForexReady;
  const readyRef = useRef(onMenuReady);
  readyRef.current = onMenuReady;

  useEffect(() => {
    const root = rootRef.current!;
    const q = <T extends Element>(c: string) => root.querySelector(".cin-" + c) as unknown as T;
    // 1.44.1: intro = <video> (kontrakt, z którego silnik korzysta od REF_C: play / pause / currentTime / ended / error)
    const intro = q<HTMLVideoElement>("intro");
    const el: MenuElements = {
      root, canvas: q("universe"), video: intro, cinema: q("cinema"), menu: q("menu"), selected: q("selected"), selectedName: q("selected-name"),
      selectedNote: q("selected-note"), returnBtn: q("return"), skip: q("skip"), videoStart: q("video-start"), progress: q("cinema-progress"),
      progressBar: root.querySelector(".cin-cinema-progress span") as HTMLElement, notice: q("notice"), announcer: q("announcer"),
      rendererError: q("renderer-error"), rendererMessage: q("renderer-message"), rendererRetry: q("renderer-retry"),
      buttons: [q("mode-forex"), q("mode-crypto"), q("mode-otc")], replay: q("replay"), sound: q("sound"), motion: q("motion"), fullscreen: q("fullscreen"),
    };
    const soft = forceSoftware || new URLSearchParams(location.hash.split("?")[1] || "").get("renderer") === "cpu";
    const dispose = mountMenu(el, {
      playIntro: testIntro || shouldPlayIntro(), reduced: testIntro ? false : prefersReducedMotion(), forceSoftware: soft,
      audio: soundOn(), onSoundChange: saveSound,
      onChoose: (_m: Mode) => undefined,
      onMenuReady: () => readyRef.current?.(),
      onForexReady: (pose) => {
        if (forexRef.current) { forexRef.current(pose); return; }
        el.selectedNote.textContent = "Kula FOREX – ekran FOREX zostanie podłączony w etapie E2 (przelot i 4 planety).";       // tymczasowo do E2
        el.returnBtn.focus({ preventScroll: true });
      },
    });
    return () => {
      dispose();
      try { intro.pause(); intro.removeAttribute("src"); intro.load(); } catch { /* element już odpięty */ }   // zwolnij bufor filmu (ok. 28 MB)
    };
  }, [forceSoftware, testIntro]);

  return (
    <div className="app-cinematic" data-state="boot" ref={rootRef} data-testid="page-menu">
      <canvas className="cin-universe" data-testid="cinematic-menu" role="img" aria-label="Trzy srebrne planety z cząsteczek na tle gwiazd: FOREX z pierścieniem i czterema księżycami, CRYPTO z bloków z łańcuchem bloków na orbicie, OTC z rdzeniem w powłoce. Tryby wybiera się przyciskami FOREX, OTC i CRYPTO." />
      <div className="cin-vignette" aria-hidden="true" />
      <main className="cin-menu" aria-label="Wybierz tryb pracy bota" inert>
        <header className="cin-masthead"><h1>PEPEMARKETWIZARD <span className="team">TEAM</span></h1><p className="cin-motto">They call us cult but we are something more</p></header>
        <button className="mode cin-mode-forex" type="button" data-mode="FOREX" aria-label="Wybierz tryb FOREX. Przeciągnij, aby obracać kulę." aria-pressed="false" data-testid="menu-forex">
          <span className="label"><span className="number">01</span><span className="mode-name">FOREX</span><span className="enter-mark" /></span></button>
        <button className="mode cin-mode-crypto" type="button" data-mode="CRYPTO" aria-label="Wybierz tryb CRYPTO. Przeciągnij, aby obracać kulę." aria-pressed="false" data-testid="menu-crypto">
          <span className="label"><span className="number">02</span><span className="mode-name">CRYPTO</span><span className="enter-mark" /></span></button>
        <button className="mode cin-mode-otc" type="button" data-mode="OTC" aria-label="Wybierz tryb OTC. Przeciągnij, aby obracać kulę." aria-pressed="false" data-testid="menu-otc">
          <span className="label"><span className="number">03</span><span className="mode-name">OTC</span><span className="enter-mark" /></span></button>
        <div className="cin-menu-hint">PRZECIĄGNIJ, ABY OBRÓCIĆ<span className="hint-separator">·</span>KLIKNIJ, ABY WYBRAĆ</div>
      </main>
      <section className="cin-selected" aria-label="Wybrany tryb" inert data-testid="menu-selected">
        <div className="cin-selected-top">PEPEMARKETWIZARD TEAM</div>
        <button className="cin-return" type="button" data-testid="menu-return"><span aria-hidden="true">⟵</span> POWRÓT DO MENU</button>
        <div className="cin-selected-label"><p className="eyebrow">WYBRANY TRYB PRACY</p><h2 className="cin-selected-name">FOREX</h2>
          <p className="cin-selected-note">{PREPARING_NOTE}</p></div>
      </section>
      <div className="cin-presentation-mark">PEPEMARKETWIZARD {s.app_version ? "/ " + s.app_version : ""}</div>
      <div className="cin-cinema" title="Kliknij, aby pominąć intro"><video className="cin-intro" data-testid="intro-video" src={introFilm} preload="metadata" playsInline
        disablePictureInPicture disableRemotePlayback controlsList="nodownload nofullscreen noremoteplayback" tabIndex={-1}
        aria-label="Film startowy PepeMarketWizard. Kliknij, naciśnij Spację albo Esc, aby przejść do menu." /><span className="cin-cinema-label">PEPEMARKETWIZARD / INITIATION</span></div>
      <button className="cin-video-start" type="button" hidden>URUCHOM INTRO</button>
      <button className="cin-skip" type="button" data-testid="intro-skip">PRZEJDŹ DO MENU</button>
      <div className="cin-cinema-progress" aria-hidden="true"><span /></div>
      <nav className="cin-tools" aria-label="Sterowanie">
        <button className="tool cin-replay" type="button" aria-label="Odtwórz intro ponownie" data-label="Odtwórz intro ponownie (R)"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6a7 7 0 1 1-1 7M4 2v4h4" /></svg></button>
        <button className="tool cin-sound" type="button" aria-label="Wycisz intro" aria-pressed="true" data-label="Wycisz intro" data-testid="intro-sound"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M9 4 5 8H2v4h3l4 4zM13 7l5 6m0-6-5 6" /></svg></button>
        <button className="tool cin-motion" type="button" aria-label="Ogranicz ruch" aria-pressed="false" data-label="Ogranicz ruch"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 4v12m6-12v12" /></svg></button>
        <button className="tool cin-fullscreen" type="button" aria-label="Pełny ekran" data-label="Pełny ekran"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 7V3h4m6 0h4v4m0 6v4h-4m-6 0H3v-4" /></svg></button>
      </nav>
      <div className="cin-notice" role="status" /><div className="cin-announcer sr-only" aria-live="polite" />
      <div className="cin-renderer-error" role="alert" hidden><h2>Renderer 3D jest niedostępny</h2>
        <p className="cin-renderer-message">Włącz akcelerację sprzętową w przeglądarce i otwórz ponownie panel. Menu potrzebuje dostępnego kontekstu graficznego przeglądarki.</p>
        <button className="cin-renderer-retry" type="button">SPRÓBUJ PONOWNIE</button></div>
    </div>
  );
}
