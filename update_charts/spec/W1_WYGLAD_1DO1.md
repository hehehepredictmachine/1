# W1 – Wygląd 1:1 z wizualizacją

Decyzja użytkownika (POTWIERDZONE): panele CHARTS wyglądają **dokładnie 1:1** jak w wizualizacji, ze wszystkimi szczegółami, łącznie z wyglądem wykresu i powiadomień o sygnałach.

## 1. Metoda: przeniesienie, nie odtworzenie

| Warstwa | Plik wzorca | Jak przenosisz |
|---|---|---|
| Znaczniki | `referencje/kod/charts_wzorzec/charts.html` | JSX z tą samą strukturą, `id`, klasami, `role`, `aria-*`, `data-*`. Teksty etykiet bez zmian |
| Wygląd | `charts.css` | kopia bez zmian wartości. Wolno dodać prefiks `#charts-screen` do selektorów ogólnych (`.segb`, `.sw`, `.seg`, `.note`…), jeśli kolidują z resztą aplikacji |
| Rysowanie | `charts.js` | `drawMain`, `drawBotLayers`, `drawKronos`, `placeCard`, `renderOpts`, `hitSignal`, `svpRecalc`, `svpVisible`, odczyty i obsługa myszy – moduły TS 1:1. Wolno: typy, podział na pliki, importy. Nie wolno: zmieniać stałych, kolorów, czcionek, grubości linii, kolejności rysowania, progów i tekstów |
| Ruch | `chartsPlanet`, `CH.swap`, `CH.flash`, `K.anim`, `uiA` | te same czasy i krzywe |

Pomocnicze funkcje wzorca spoza wycinka (`$`, `$$`, `smooth`, `seg`, `easeIO3`, `announce`, `rectOf`) bierzesz z pełnego `REF_B` (lub ze wspólnego modułu, jeśli już istnieje w wariancie A z tą samą matematyką).

Silnik: **canvas 2D z kodu wzorca.** `lightweight-charts` nie jest używany na tym ekranie, bo nie da wyglądu 1:1 (inne świece, osie, etykiety, kursor).

## 2. Zmiany względem wzorca – jedyne dozwolone

1. Dane: z API zamiast `BOTDATA` / generatorów (D1).
2. Teksty o pochodzeniu danych: notka karty planu i znacznik w nagłówku (D1 §0, K3 §7).
3. Elementy demo usunięte (K3 §9) – na ich miejscu wiersz „NIEDOSTĘPNE” w stylu `UNAVAIL`, jeśli wzorzec go ma, inaczej brak elementu.
4. Stany puste (D1 §0) – w stylu wzorca (`.note`, kolory przygaszone).

Wszystko inne – identyczne.

## 3. Elementy objęte zgodnością (lista kontrolna)

- **Nagłówek:** „01 — CHARTS”, separatory, przełącznik instrumentu, TF z kropkami, BID / ASK / SPREAD, wybór czasu, status MT5 z pulsującą kropką.
- **Okno główne:** ramka `.cs-win` z narożnikami, tytuł „XAUUSD- · M5 WYKRES GŁÓWNY”, podpowiedź „PRZECIĄGNIJ · KÓŁKO = ZOOM · 2× KLIK = TERAZ”, odczyt OHLC i wskaźników, świece, wolumen, EMA, AVWAP ±σ, siatka, oś ceny ze znacznikiem, oś czasu, okna RSI 14 i MACD 12·26·9.
- **Warstwy bota:** markery ▲▼ z podpisami, etykieta wejścia, poziomy planu z R, strefy z etykietą „typ · TF · Q · stan”, boksy sesji, profile sesji (POC, VA, HVN, LVN, etykieta „W TOKU”), etykieta „KRONOS M5 +12”.
- **Karta PLAN BOTA:** szerokość 330 px, nagłówek z chipem, siatka poziomów 3 kolumny, sekcje, wiersze szans z paskiem, notka, zwijanie.
- **Kronos:** zakładki TF, „TRYB AUTO”, „PRZELICZ”, świece, linia TERAZ, prognoza, wachlarz, znacznik ceny, stopka (kierunek ze strzałką, delta, ścieżki, pasmo neutralne, czas, „SHADOW, bez zleceń”).
- **Panel opcji:** 6 zakładek z podkreśleniem, przełączniki `.sw`, segmenty `.seg`, koszyki `.bk` z rozwijaniem, wiersze strategii ze stanem i „→ M5”, tabela profili.
- **Przycisk powrotu** i ikona ustawień w rogach.

## 4. Jak sprawdzić
Test pikselowy `narzedzia/charts_1do1/` (K6) + przegląd interakcji (K6 §2).
