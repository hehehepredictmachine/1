# Claude Code — PepeMarketWizard Main Menu V2 (8 Towers)

## Cel
W istniejącej aplikacji PepeMarketWizard wdroż **wyłącznie ekran menu głównego** według załączonego podglądu `index.html` i referencji `assets/neural_wolf_table.png`.

## Obowiązkowy wygląd
- Usuń wszystkie dotychczasowe panele informacyjne z ekranu głównego (w tym wykresy, portfolio, mini-wykresy i inne boczne karty). Nie usuwaj odpowiadających im usług backendowych ani modułów docelowych.
- Usuń wszystkie dolne przyciski i dawny launcher w obrębie samego ekranu menu.
- Pomniejsz logo PepeMarketWizard i ustaw je w **lewym górnym rogu**.
- Umieść pasek nawigacyjny **na górze**, z odnośnikami do wszystkich 8 modułów.
- Zachowaj trzech Pepe w ciemnych garniturach, siedzących przy dużym okrągłym, neonowym stole z sieci neuronowych.
- Ustaw **osiem** osobnych, futurystycznych wież na stole, każda z jednoznaczną etykietą i niezależnym klikalnym obszarem.
- Główna scena ma pozostać ekranem menu — nie buduj zawartości wnętrz wież w tym zadaniu.
- Stół zawiera animowany mózg neuronowy i świetlne połączenia do każdej wieży.

## Osiem przycisków / nawigacja
| UI | Identyfikator semantyczny | Docelowe miejsce |
| --- | --- | --- |
| PEPE$WTC | pepe-wtc | wykresy, MT5, modele, Kronos |
| PEPE$SIGNAL | pepe-signal | sygnały i oceny AI |
| PEPE$BANK | pepe-bank | pełne informacje i historia sygnałów |
| PEPE$ROI | pepe-roi | rozliczone transakcje i statystyki |
| STRATEGIES | strategies | strategie i Auto Mode |
| MARKET NEWS | market-news | wiadomości i makro |
| TRAINING LAB | training-lab | eksport, walidacja i trening modeli |
| SETTINGS | settings | ustawienia i połączenia |

Podłącz przyciski zarówno na wieżach, jak i w pasku nawigacyjnym do **istniejącego routera** aplikacji. Przed zmianą nazw sprawdź stare i nowe ścieżki; zachowaj przekierowania i kompatybilność.
Jeśli moduł nie istnieje w repozytorium, wyświetl informację o braku podłączonej sekcji, nie twórz fikcyjnej implementacji. Nie modyfikuj logiki tradingowej.

## Interakcje i animacje
- Każda wieża reaguje na hover, focus i kliknięcie; aktywacja wysyła puls po neuronowej ścieżce.
- Docelowo wieże mają być niezależnymi modelami 3D, z subtelnym obrotem wokół własnej osi. Aktualny HTML jest prototypem 2.5D z interaktywnymi obszarami na obrazie, a nie gotową geometrią 3D. W finalnej aplikacji można zastosować Three.js/React Three Fiber, ale należy zachować kompozycję referencji.
- Animacja Pepe może reagować na kursor/kliknięcia. Aby poruszać rękami i liczyć banknoty jako prawdziwy model 3D, potrzebny jest model szkieletowy z animacjami — nie przedstawiaj animacji nakładkowej jako pełnego riga.
- Przy aktywacji wybranej wieży uruchom lekki efekt portalu. Nie spowalniaj inicjalizacji rzeczywistych modułów.
- Ruch musi respektować ustawienie `prefers-reduced-motion`.
- Zapewnij nawigację klawiaturą, focus states, poprawne kontrasty i opisy dostępności.

## Integracja i wydajność
- Nie pobieraj danych MT5 na potrzeby samej animacji menu i nie wymyślaj statystyk.
- Oddziel renderer sceny od silnika tradingowego.
- Ogranicz liczbę cząsteczek, wstrzymuj zbędne animacje w tle, sprzątaj requestAnimationFrame i zasoby WebGL po odmontowaniu.
- Zachowaj responsywność; priorytet desktop 16:9, inne formaty bez rozciągania renderingu.

## Kryteria akceptacji
1. Brak dawnych paneli na ekranie głównym i brak przycisków na dole.
2. Małe logo w górnym lewym rogu, pasek nawigacji na górze.
3. Trzy widoczne postacie i okrągły neuronowy stół.
4. Dokładnie osiem wież z osobnymi interakcjami.
5. Każda wieża i nazwa w pasku kieruje do tej samej właściwej sekcji.
6. Działa powrót z sekcji, obsługa klawiatury i ograniczenia animacji.
7. Testy desktop i mobile, brak błędów konsoli oraz wycieków zasobów.
8. Dostarcz raport z zaimplementowanych integracji i braków. Nie deklaruj zgodności 3D, jeśli używasz obrazka 2.5D.

**Wdrożenie:** najpierw audyt aktualnego repozytorium, potem integracja layoutu menu i tras, następnie animacje, na koniec testy i raport. Zmieniaj tylko pliki niezbędne dla menu głównego.
