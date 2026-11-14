// Markup of the approved Galaxy V2 reference (PepeMarketWizard_GALAXY_FULL_NEURAL_MESH_V2.html), assets served from /assets/galaxy/.
// Static string - no user data is interpolated.
export const GALAXY_MARKUP = String.raw`<div class="gx-app">
 <header class="topbar">
  <div class="brand"><img class="brand-logo" src="/assets/galaxy/logo.webp" alt="Logo Pepe Czarodziej"><div><div class="brand-name"><span class="g">Pepe</span>Market<span class="p">Wizard</span></div><div class="brand-caption">GALACTIC INTERFACE · FULL NEURAL MESH</div></div></div>
  <nav class="nav" aria-label="Menu główne"><button class="active" data-route="home"><span class="ni">⌂</span> Main Menu</button><button data-route="pepe-wtc"><span class="ni">◫</span> Trading</button><button data-route="modele"><span class="ni">♧</span> Models</button><button data-route="sygnal"><span class="ni">◉</span> Signals</button><button data-route="lightning"><span class="ni">▤</span> PEPE$BANK</button><button data-route="ustawienia"><span class="ni">⚙</span> Settings</button></nav>
  <div class="actions"><div class="status" id="gxStatus" data-testid="gx-status" data-tone="warn"><i class="dot"></i> <span>UNKNOWN</span></div><button class="icon-btn" id="playBtn" title="Wstrzymaj/wznów animacje" aria-label="Wstrzymaj/wznów animacje">Ⅱ</button><button class="icon-btn" id="editBtn" title="Edytuj galaktykę" aria-label="Włącz edytor">✎</button><button class="icon-btn" id="fullBtn" title="Pełny ekran" aria-label="Pełny ekran">⛶</button></div>
 </header>
 <main class="stage">
  <aside class="side" id="sideLeft" style="background-image:url('/assets/galaxy/left.webp')" aria-label="Efekt wizualny aktywności modeli AI"><div class="side-head"><span class="chip">♧</span><div><strong>AI MODELS<br>PROCESSING</strong><small>VISUAL EFFECT</small></div></div><video class="side-video" id="sideVideoLeft" autoplay muted loop playsinline preload="auto" aria-hidden="true"></video><canvas id="leftCanvas"></canvas></aside>
  <div class="space" id="space" aria-label="Interaktywne menu galaktyczne PepeMarketWizard">
   <div class="space-bg" id="spaceBg"></div><div class="galaxy-glow"></div><div class="mesh-indicator" aria-live="off"><i class="mesh-led"></i><strong>FULL NEURAL MESH</strong><span class="links" id="meshCount">21 / 21</span></div><canvas id="galaxyCanvas"></canvas><div class="planet-layer" id="planetLayer"></div>
   <div class="edit-pill">EDYTOR NA ŻYWO · PRZECIĄGAJ PLANETY</div>
   <div class="galaxy-caption"><b>● GALAXY NAVIGATION</b><span>•</span><span id="caption">Wybierz planetę, aby otworzyć sekcję</span></div>
   <div class="floating-tools"><button id="centerBtn" title="Przywróć rozmieszczenie planet">⟲ Widok</button><button id="editorFloatBtn" title="Otwórz ustawienia">⚙ Projektuj</button></div>
  </div>
  <aside class="side" id="sideRight" style="background-image:url('/assets/galaxy/right.webp')" aria-label="Efekt wizualny działania silnika AI"><div class="side-head"><span class="chip">♧</span><div><strong>AI ENGINE<br>RUNNING</strong><small>VISUAL EFFECT</small></div></div><video class="side-video" id="sideVideoRight" autoplay muted loop playsinline preload="auto" aria-hidden="true"></video><canvas id="rightCanvas"></canvas></aside>
 </main>
 <div class="bottom" id="bottom"><canvas id="lightningCanvas"></canvas><div class="bottom-meta">PEPEMARKETWIZARD · <span>GALAXY NAVIGATION · EFEKT WIZUALNY</span></div></div>
</div>
<aside id="inspector" aria-label="Edytor galaktyki">
 <div class="ins-head"><div><strong>✦ PEPE UI STUDIO</strong><small>Edycja na żywo • wszystko w panelu</small></div><button id="closeEditor" class="icon-btn" title="Zamknij panel">×</button></div>
 <div class="ins-body">
  <div class="ins-h" style="margin-top:0">WYBRANA PLANETA</div>
  <label for="selectPlanet">Wybierz sekcję</label><select id="selectPlanet"></select>
  <label for="planetName">Nazwa na planecie</label><input id="planetName" type="text" maxlength="28" placeholder="Nazwa sekcji">
  <label for="planetRoute">Sekcja bota (ekran)</label><select id="planetRoute" data-testid="gx-route"></select>
  <label for="planetColor">Kolor podświetlenia</label><input id="planetColor" type="color" value="#aa5cff">
  <label class="range-line" for="planetSize">Rozmiar planety <strong id="sizeValue">100%</strong></label><input id="planetSize" type="range" min="55" max="170" step="5" value="100">
  <label class="range-line" for="planetX">Pozycja pozioma <strong id="xValue">50%</strong></label><input id="planetX" type="range" min="5" max="95" step="1" value="50">
  <label class="range-line" for="planetY">Pozycja pionowa <strong id="yValue">50%</strong></label><input id="planetY" type="range" min="9" max="91" step="1" value="50">
  <div class="ins-h">ANIMACJE I EFEKTY</div>
  <label class="range-line" for="speedRange">Prędkość ruchu <strong id="speedValue">100%</strong></label><input id="speedRange" type="range" min="0" max="250" value="100" step="10">
  <label class="toggle-row">Animuj galaktykę <input type="checkbox" id="animateToggle" checked></label>
  <label class="toggle-row">Pełna sieć planet · każda z każdą <input type="checkbox" id="connectionsToggle" checked></label>
   <label class="range-line" for="neuralIntensity">Intensywność włókien <strong id="neuralIntensityValue">135%</strong></label><input type="range" id="neuralIntensity" min="60" max="180" value="135" step="5">
  <label class="toggle-row">Boczne animacje modeli <input type="checkbox" id="sidesToggle" checked></label>
  <label class="toggle-row">Dolne błyskawice <input type="checkbox" id="lightningToggle" checked></label>
  <label class="toggle-row">Gwiazdy i cząsteczki <input type="checkbox" id="starsToggle" checked></label>
  <div class="ins-h">PROJEKT</div>
  <div style="display:flex;flex-wrap:wrap;gap:7px"><button class="small-btn primary" id="addPlanet">＋ Planeta</button><button class="small-btn danger" id="deletePlanet">Usuń planetę</button><button class="small-btn" id="exportBtn">↓ Eksport JSON</button><button class="small-btn" id="importBtn">↑ Import JSON</button><button class="small-btn" id="resetBtn">↺ Reset projektu</button><button class="small-btn" id="neuralCityBtn" data-testid="gx-neural-city">✶ Neural City (poprzednie menu)</button></div>
  <p style="font-size:10px;color:#9295b5;line-height:1.55;margin-top:18px">Kliknij planetę, a następnie przeciągnij ją w nowe miejsce. Zmiany są widoczne natychmiast i zapisywane lokalnie w przeglądarce. Pole „Sekcja bota” wybiera ekran, który otwiera planeta.</p>
 </div><div class="ins-foot"><button id="exitEdit" class="small-btn primary">✓ Zakończ edycję</button><button id="pauseEdit" class="small-btn">Ⅱ Animacja</button></div>
</aside>
<div class="section-modal" id="sectionModal" role="dialog" aria-modal="true" aria-labelledby="modalTitle" aria-hidden="true"><div class="section-box"><div class="modal-top"><div><div class="modal-kicker">PEPEMARKETWIZARD / GALAXY NAVIGATION</div><h2 class="modal-title" id="modalTitle">WTC PEPE</h2></div><button class="close-x" id="closeModal" aria-label="Zamknij">×</button></div><div class="modal-content"><p id="modalDesc"></p><div class="demo-card-row" id="modalCards"></div><div class="demo-note">Planeta bez przypisanej sekcji nie otwiera żadnego ekranu – nie pokazujemy makiet.</div><div class="demo-action"><button id="backToGalaxy" class="small-btn primary">← Wróć do galaktyki</button></div></div></div></div>
<div class="toast" id="toast" role="status"></div><input id="importInput" type="file" accept="application/json,.json" hidden>
`;
