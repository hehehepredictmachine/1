# E9 – Odbiór

1. Uruchom aplikację w trybie syntetycznym (`07_START_DEMO_DANE_SYNTETYCZNE.bat` albo odpowiednik) i, jeśli to możliwe, z terminalem MT5 w trybie PAPER.
2. Przejdź **całą listę `spec/S5_KRYTERIA_ODBIORU.md`**. Przy każdym punkcie wpisz ✅ / ❌ / ⚠️ z krótkim dowodem: zrzut, fragment odpowiedzi API (bez danych konta: liczby możesz zamaskować) albo log testu.
3. Zrzuty porównawcze (1600×900, DPR 1) dla ekranów menu, przelot, FOREX, CHARTS, SIGNALS, MODELS (4 zakładki), ROI (z danymi i BRAK DANYCH), 4 paneli systemowych i nowego okna startowego Windows. Wzorzec obok aplikacji w jednym pliku PNG na ekran w `update_1_42/raport/`.
4. Pomiary: średni czas klatki na każdym ekranie, liczba kontekstów WebGL po 10 cyklach nawigacji, rozmiar `dist` przed i po.
5. Raport końcowy `update_1_42/raport/RAPORT_1_42_0.md`:
   - lista zmienionych / dodanych / przeniesionych plików;
   - odstępstwa od wzorców z uzasadnieniem;
   - otwarte punkty DO WERYFIKACJI;
   - instrukcja wycofania (gałąź git albo kopia z E0).
6. Zainstaluj zbudowaną paczkę DESKTOP 1.42.0 na czystym folderze (albo w maszynie testowej), uruchom exe i przejdź start: okno startowe → WEJDŹ → intro → menu → FOREX → STOP.
7. Nie zamykaj etapu, jeśli którykolwiek punkt grupy **D (uczciwość danych)** albo **F (panele systemowe)** jest ❌.
