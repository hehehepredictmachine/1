// Kiedy grać film intro (E1, S2 §1):
//  * raz na sesję przeglądarki (sessionStorage "pmw.cinematic.seen");
//  * przeglądarka sterowana automatem (navigator.webdriver) – bez intro, chyba że localStorage "pmw.cinematic.force" = "1"
//    (testy UI nie czekają na film; tak samo działał BootScreen 1.39);
//  * ograniczenie ruchu – silnik od razu przechodzi do menu;
//  * „Odtwórz intro”, klawisz R i Ctrl+Alt+B grają je ponownie (obsługa w menuEngine).
const SEEN = "pmw.cinematic.seen";
const FORCE = "pmw.cinematic.force";

export function introForced(): boolean {
  try { return localStorage.getItem(FORCE) === "1"; } catch { return false; }
}

export function shouldPlayIntro(): boolean {
  try {
    if (introForced()) return true;
    if ((navigator as any).webdriver) return false;
    return sessionStorage.getItem(SEEN) !== "1";
  } catch {
    return !(navigator as any).webdriver;
  }
}

export function markIntroSeen(): void {
  try { sessionStorage.setItem(SEEN, "1"); } catch { /* pamięć sesji zablokowana – intro zagra ponownie, nic więcej */ }
}

export function prefersReducedMotion(): boolean {
  try {
    if (localStorage.getItem("pmw.motion") === "reduced") return true;
    if (localStorage.getItem("pmw.motion") === "full") return false;
  } catch { /* brak pamięci – decyduje system */ }
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function saveMotionChoice(reduced: boolean): void {
  try { localStorage.setItem("pmw.motion", reduced ? "reduced" : "full"); } catch { /* bez trwałości */ }
}

/** Hak testowy (S1 §2): dostępny tylko w przeglądarce sterowanej automatem albo przy localStorage "pmw.test" = "1". */
export function testMode(): boolean {
  try { return !!(navigator as any).webdriver || localStorage.getItem("pmw.test") === "1"; } catch { return !!(navigator as any).webdriver; }
}
