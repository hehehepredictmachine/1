# Zmienność dzienna i IV walls (MQ-VOLZONES-1.0.0)

Kod: `backend/masterquo/engine/volzones.py`, API `GET /api/v1/volatility`, dane dołączane do każdego `/api/v1/candles`,
narzędzie agenta `get_volatility_levels`, ustawienia: **Ustawienia → Zmienność / IV** (`data\config.json`, sekcja `volatility`).

## Co bot wyznacza (z D1 Twojego symbolu `XAUUSD-`, ceny Bid)
| Poziom | Jak liczony |
|---|---|
| **Daily Open** | otwarcie bieżącego dnia brokera (tworząca się świeca D1) |
| **High / Low dnia** | dotychczasowe maksimum/minimum dnia |
| **PDH / PDL** | high / low poprzedniego dnia |
| **HV** | zmienność historyczna z `window` (domyślnie 20) **zamkniętych** świec D1: close-to-close (log-zwroty, odchylenie próbkowe) albo Parkinson (high/low); ×√252. Bieżący dzień nigdy nie wchodzi (brak zaglądania w przyszłość). Percentyl 1R = jak wysoka jest dzisiejsza HV na tle ostatniego roku. |
| **IV do wyceny** | MT5 nie ma łańcucha opcji na złoto → domyślnie IV = HV. Opcja `MANUAL`: wpisujesz IV z innego źródła (np. indeks GVZ). |
| **Daily High / Low (IV 1σ)** | Daily Open × e^(±σ·√T), T = 1/252 – oczekiwany zakres dnia (≈68% dni kończy się w środku, przy założeniach modelu) |
| **Straddle ATM** | wycena 1-dniowych opcji Black-76 (r = 0, forward = Daily Open): call + put ATM = rynkowo „wyceniony” ruch dnia; progi rentowności Daily Open ± straddle |
| **IV walls ±kσ** | strefy wokół Daily Open × e^(±k·σ·√T) dla k z `walls_sigma` (domyślnie 1 i 2), szerokość ±`wall_band_sigma`·σ√T. Dla każdej: premia opcji (call w górę, put w dół), delta, P(zamknięcie dnia za poziomem) = N(d2), P(dotknięcie w ciągu dnia) ≈ 2·N(d2), znacznik „osiągnięty”. |
| **Wykorzystany zakres** | (High − Low dnia) / (Daily High − Daily Low IV 1σ) |

Gdy rynek jest zamknięty (weekend), poziomy są projekcją na następną sesję od ostatniego zamknięcia.

## Na monitorze
* Przełącznik **„IV walls / Daily”** na pasku wykresów (domyślnie włączony). Strefy IV walls (czerwona ↑, zielona ↓) od otwarcia dnia,
  linie: Daily Open (ciągła), Daily High/Low IV 1σ (gruba przerywana), Straddle BE (kropki), PDH/PDL, High/Low dnia.
  Włączenie/wyłączenie nie zmienia zoomu ani skali wykresu. Kolory: **Wygląd → Poziomy i strefy**.
* Panel **ZMIENNOŚĆ DZIENNA · IV WALLS**: wszystkie liczby i tabela wycen.

## Ograniczenia (uczciwie)
* To poziomy modelu (rozkład lognormalny, stała zmienność, brak dryfu). Nie są to zlecenia, open interest, „gamma walls” dealerów
  ani prognoza. Prawdziwe ruchy złota mają grube ogony – wyjście poza ±2σ zdarza się częściej, niż mówi model.
* Bez danych opcyjnych IV = HV, więc „IV walls” są w praktyce **HV walls**. Dokładniejsze są przy ręcznie wpisanej IV.
* Poziomy są informacją na wykresie i dla agenta – **nie zmieniają** strategii S01–S10, bramek, ryzyka ani zleceń.
