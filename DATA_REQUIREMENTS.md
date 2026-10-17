# DATA_REQUIREMENTS – czego brakuje (1.14)

| Potrzeba | Moduły | Źródło | Stan w środowisku budowania | Co zrobić |
|---|---|---|---|---|
| Historia M5 / M15 / H1 / D1 `XAUUSD-` (≥ 2 lata) | lab, badania, M01–M31 | Twój MT5 (`copy_rates_from_pos`) | brak – tylko symulator | uruchom program z MT5; badanie: Modele i trening → Uruchom badanie (pobiera do 100 000 świec M5 przez bridge) |
| Mapowanie BTC → symbol brokera | wszystko dla BTC | metadane terminala | symulator: `BTCUSD-` | Ustawienia → Aktywa → BTC: Szukaj kandydatów → Potwierdź (tylko metadane BTC/USD) |
| Historia BTC CFD i jej dostępność w weekendy | BTC | Twój MT5 | brak | jw. – dostępność odczytywana z notowań, nie zakładana |
| Ticki bid/ask (`copy_ticks_from`) | M28 ACD, M31 kinematyka, replay kosztów | Twój MT5 | syntetyczne | moduły działają na żywo; archiwum ticków do backtestu – do zebrania (kolekcja bieżąca) |
| Opcje / IV / OI na złoto | M33 | import ręczny (1.10) | brak | `IV_MANUAL` / import CSV; bez danych brak walls |
| Opcje BTC | M33 dla BTC | brak dostawcy | brak | nie zaimplementowano adaptera – brak danych |
| Liquidation heatmap | M32 | np. CoinGlass (klucz API, płatny) | brak licencji | wymaga Twojego klucza i decyzji – nic nie jest symulowane |
| IQ Gold Gann, IQ Star Lines | M34, M35 | MQL5 Market (licencja) | brak | zakup i udostępnienie buforów wskaźnika |
| PAL02M, „super candles intelligence”, MD Scalper, Extrapolator (wariant), źródło automatycznych trendlinii | M36, M37, M26, M29, M13 | nieustalone | brak plików | wskaż konkretne pliki lub URL; do tego czasu `blocked` lub własna metoda |
| Treść artykułów MQL5 i prac naukowych R01–R44 | dokumentacja | internet | zablokowane | ponowna weryfikacja z sieci z dostępem |

**Zasady:**
- Brak danych nie zamienia się w zero ani w syntetyczny substytut w wynikach.
- Dane syntetyczne służą wyłącznie testom kodu.
