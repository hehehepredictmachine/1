# 1.40 – optymalizacja interfejsu (pomiary, nie szacunki)

Środowisko pomiaru: Chromium headless 1920×1080, 4 vCPU, 16 GB RAM, **renderowanie programowe (bez GPU)** – najgorszy przypadek; na komputerze z GPU
wartości są wyższe. Ten sam backend demo; 1.39 = wydanie 1.39.0 (git `33c28cf`), 1.40 = to wydanie. Okno pomiaru 8 s po 4 s rozgrzewki
(`requestAnimationFrame` / s, długie zadania > 50 ms przez PerformanceObserver, pamięć JS).

| Ekran | Wersja | FPS | długie zadania (blokada) | canvasy | filmy |
|---|---|---|---|---|---|
| Menu Galaxy | 1.39 | **0,7** | 6 (≈ 8,0 s) | 4 | 2 |
| Menu Galaxy | 1.40 | **17–34** (jakość „low” / „high”) | 5 (≈ 4,5 s w oknie z przełączeniem jakości) | 4 | 2 |
| WTC$PEPE | 1.39 (stary układ) | 60 | 0 | 54 | 0 |
| WTC$PEPE | 1.40 (układ z paczki, film tła) | 47–58 | 0 | 15 | 1 |

Rozbicie kosztu menu (1.40, wyłączanie kolejnych elementów): wszystko 34 FPS → bez filmów bocznych 48 → bez animacji CSS dekoracji 59–60.
W 1.39 głównym kosztem były: dwa filmy 720×1280 dekodowane dla paneli szerokości ~170 px, ~400 rozmytych (`shadowBlur`) pociągnięć na klatkę
(rasteryzacja nie jest widoczna w czasie JS), `mix-blend-mode` / `filter` na warstwach zmieniających się co klatkę, obracająca się warstwa z `blur(52px)`
i przesuwanie planet przez `left/top` (layout całej strony w każdej klatce).

Zmiany:
* Menu Galaxy: film boczny przeskalowany do 240×426 / 24 kl./s (3,6 MB → 0,4 MB, wygląd w panelu bez zmian); bez `backdrop-filter`, bez blend / filter
  na canvasach i filmach; poświata statyczna; planety przez `transform: translate3d` (rozmiar / kolor zmieniane tylko przy zmianie); DPR ≤ 1,25;
  **adaptacyjna jakość** wg rzeczywistego odstępu klatek (> 40 ms → tryb lite: bez rozmycia cieni, mniej włókien i cząstek, 30 FPS, bez filmów i
  dekoracyjnych animacji CSS; po 20 s próba powrotu, maks. 2 razy). Rysowanie stoi, gdy karta jest ukryta lub widoczne jest intro.
* WTC$PEPE: film tła 1280×720 / 60 kl./s → 960×540 / 24 kl./s (4,9 → 1,1 MB), wstrzymywany na ukrytej karcie, przełącznik „TŁO ON/OFF”,
  wyłączony przy ograniczonych animacjach systemu; bez rozmycia tła kart; Chart Lab montowany dopiero po „CUSTOMIZE CHART” i bez przebudowy wykresu,
  gdy odpytanie co 15 s zwraca te same świece; wykresy Multi-Chart tworzone dopiero, gdy są widoczne (IntersectionObserver) – 54 → 15 canvasów.
Skrypty pomiarowe: uruchamiane jak testy UI (Playwright), wyniki powtarzalne w granicach ±5 FPS.
