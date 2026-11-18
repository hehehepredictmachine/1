# SC1 – Scenariusz i oś czasu

Źródło prawdy: `referencje/kod/intro3d/intro.js` (`TL`, `START`, `update(t)`). Tabela opisuje to samo słowami. Czas całkowity **13,8 s**.

| t [s] | Co widać | Mechanika (wzorzec) |
|---|---|---|
| 0,0–2,4 | wyjście z czerni, galaktyka i mgławice rozjaśniają się | `uFade` 0→1; galaktyka `uB` 0→1 (0,2–3,4 s), mgławice 0,6–4,2 s; mgła `FogExp2` 0,07 → 0,035 do 7 s; światła tylne rosną 0,3–3,2 s |
| 0,0–5,7 | trzy postacie w garniturach idą w stronę widza po lustrzanej tafli w kosmosie | start: środkowa `z −15,3`, boczne `x ∓1,08 / 1,1`, `z ≈ −15,8`; prędkość 1,32 m/s, kadencja 1,82–1,9 kroku/s, przesunięte fazy |
| 5,5–7,3 | hamowanie i zatrzymanie **w połowie drogi** (≈ 7 m od widza) | `TL.stop`: lewa 5,5 + 1,45 s, środkowa 5,7 + 1,5 s, prawa 5,85 + 1,5 s; potem oddech i lekki ruch ciężaru |
| 6,6–7,8 | środkowa postać lekko spuszcza wzrok | `look` głowy |
| 7,0–8,7 | **3 planety** składają się z cząstek w rzędzie przed środkową postacią (wys. 1,3 m) | `TL.planetsIn`, cząstki lecą z rozproszenia (`aStart`) do kształtu |
| 8,0–9,4 | boczne postacie odwracają głowy ku planetom | `look` bocznych |
| 8,5–10,2 | środkowa sięga **prawą ręką**, pochyla się | IK CCD ramienia + orientacja dłoni (wnętrze w dół, palce od ciała) |
| 8,7–10,0 | planety zbliżają się w trójkąt pod dłonią | `TL.gather` |
| 10,2 | **dłoń na planetach** | puls cząstek, pierścień światła, światło planet rośnie |
| 10,5–13,3 | najazd kamery na dłoń, planety i twarz w kominiarce | `TL.push`; pasy kinowe chowają się |
| 12,7–13,8 | błysk | `uFlash` |
| 13,8 | koniec → zdarzenie `ended` → menu wchodzi (faza `enter` menu) | menu przyciemnia i powiększa płótno intro, z centrum wchodzi planeta FOREX |

## Kamera
Widz siedzący: kamera `y 1,12 m`, `z 0`, `fov 30°` (ekran węższy niż 1,5:1 → 38°), lekki „oddech” (`sin`). Najazd: do punktu `(cx+0,12; cy+0,06; cz+1,75)` z celem `(cx; cy+0,2; cz−0,1)`, `fov → 36°`.

## Otoczenie: galaktyka (`galaxy.js`)
- pole 9000 gwiazd na sferze (migotanie zależne od `t`);
- galaktyka spiralna 2-ramienna: 70 000 gwiazd w ramionach + 16 000 w zgrubieniu, w lewym górnym rogu kadru (`(-52, 40, -185)`, skala 0,62), powolny obrót zależny od `t`; rdzeń ciepły, ramiona niebiesko-fioletowe, różowe obszary HII;
- poświata rdzenia i 7 mgławic (tekstury szumu generowane w kodzie, fiolet / błękit / róż);
- podłoga: lustro (`Reflector`, 900×900 m, 1024²) pod półprzezroczystą warstwą (78 %) – postacie idą po ciemnej tafli odbijającej galaktykę.

## Światło
- reflektor tylny ciepły (od strony galaktyki) i chłodny niebieski, oba z cieniami 1024²; reflektor górny; „światło ekranu” od strony widza; wąski czerwony kontur na kominiarce; półsfera bardzo słaba.
- Światło punktowe planet pod dłonią rośnie przy dotyku.

## Postprocessing (kolejność)
`RenderPass` → `UnrealBloomPass` (siła 0,40 → +dotyk/puls, próg 1,0) → `OutputPass` (ACES, sRGB) → przebieg końcowy: lekka aberracja chromatyczna, winieta, ziarno (zależne od `t` – deterministyczne), wejście z czerni, błysk, pasy kinowe 8,5 % (tylko ekran ≥ 1,5:1).
