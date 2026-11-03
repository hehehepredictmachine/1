> **1.30.0:** system licencji opisany w §2 i §5 (License Manager, serwer licencji, wersja CLIENT, KEY FOR MAGIC) został **usunięty**
> na Twoją prośbę – program działa bez klucza. Wykresy, strefy, interfejs i narzędzia wydania z 1.29 zostają. Paczki 1.30:
> `PepeMarketWizard_DESKTOP_1_30_1.zip`, `PepeMarketWizard_1_30_1.zip` (1.30.1: poprawka panelu Neural Cyberpunk). Raport: `release/RAPORT_KONCOWY.md`.

# PepeMarketWizard 1.29.0 – licencje bez logowania, wykresy z własnymi ustawieniami, jeden interfejs w stylu wież

Realizacja pakietu aktualizacji „PepeMarketWizard – pakiet aktualizacji dla Claude” (CLAUDE_WDROZENIE.md, §0–§6). Ten dokument opisuje,
co zmieniono, jak tego używać, jak wydać paczki, jak wrócić do 1.28 i czego **nie** dało się sprawdzić w tym środowisku.
Wyniki testów (komendy, liczby): `release/RAPORT_KONCOWY.md`.

Wszystkie prace i testy wykonano na symulatorze terminala (dane SYNTETYCZNE) i w trybach SIGNALS / PAPER – **bez zleceń LIVE**,
bez prawdziwego MT5, bez Windows, bez publicznego serwera licencji.

---

## 1. Mapa przepływu (inwentaryzacja §1 – stan po 1.29)

```
MT5 (terminal) ──► bridge (mt5/bridge.py: świece, ticki, czas serwera) ──► jakość danych (M01, data_quality)
   │                                                                          │
   │  eksport (marketdata/: Parquet+CSV+manifest)                              ▼
   └──────────────► trainhub (dataset → trening → ocena → paczka) ──► rejestr modeli (modelhub, PMW-PRED-1)
                                                                              │
 cechy / strefy: zones/market.py (M1/M5/M15/M30), HLZE/DSVIE/UZICE, wskaźniki  ─┤
                                                                              ▼
 agregacja (jedna grupa korelacji = jeden głos) ──► strategie S01–S12, SCALPING, HEDGING ──► ryzyko (limity, ekspozycja, koszty)
                                                                              │
                                                     decyzja (mode_gate, STOP, licencja CLIENT, ścieżka główna)
                                                                              │
                     wykonanie: SIGNALS (bez zleceń) / PAPER / AUTO DEMO / AUTO LIVE ──► monitor (WS) + Telegram
```

Ścieżki nowych zleceń (sprawdzone w kodzie i testach licencji): każde nowe wejście (S01–S12, ręczne, SCALPING/HEDGING) przechodzi przez
bramkę trybu i – w paczce CLIENT – przez LicenseGuard. **Brak licencji lub sieci blokuje tylko nowe wejścia**; prowadzenie otwartych
pozycji (SL/TP po stronie brokera, częściowe zamknięcia, hedging, BE) działa dalej – potwierdza to `tests/test_license_acceptance.py`
(test 2: brak sieci / podmieniony klucz serwera) i istniejące testy integracji licencji z wykonaniem.

Koszty: spread – zmierzony ze świec / ticka; prowizja – tylko z historii transakcji rachunku; poślizg – jawne założenie z ustawień.
Historycznego bid/ask nie odtwarzamy z bieżących wartości.

---

## 2. Licencje – administrator bez logowania (§4)

### Co się zmieniło
* **OWNER nie ma ekranu logowania.** Aplikacja OWNER ma własny **klucz urządzenia Ed25519** (tworzony przy pierwszym użyciu). Na Windows
  klucz prywatny jest szyfrowany **DPAPI** bieżącego użytkownika (`data\license_owner_key.dpapi` – bezużyteczny na innym koncie
  i komputerze). Każde żądanie administracyjne jest **podpisane** (PMW-ADMIN-v1: metoda, ścieżka z zapytaniem, SHA-256 treści, czas UTC,
  losowy nonce, identyfikator klucza).
* **Serwer licencji 1.1.0** ufa wyłącznie kluczom dodanym **z powłoki serwera** (poza publicznym API):
  `python -m pmw_license admin-keys add --public-key <base64> --label "OWNER <komputer>"`.
  Ochrona przed powtórzeniem: okno czasu ±120 s i **trwała** tabela nonce w bazie (powtórzenie odrzucone także po restarcie serwera).
  Każde odrzucenie trafia do dziennika audytu (bez podpisów i kluczy).
* **Okresy licencji:** 72 h, 7 dni, 31 dni; 24 h jako opcja zaawansowana.
* **Rotacja / utrata komputera:** w License Manager „Rozpocznij rotację klucza” tworzy nowy klucz, dodajesz go poleceniem `admin-keys add`,
  „Zakończ rotację” sprawdza nowy klucz na serwerze i odwołuje stary. Utrata komputera: na serwerze `admin-keys list` →
  `admin-keys revoke <kid> --reason "utracony komputer"`, potem parowanie nowego komputera.
* **Hasło administratora na serwerze jest opcjonalne** (tylko dla aplikacji OWNER < 1.29); puste `PMW_LIC_ADMIN_PASSWORD_HASH`
  wyłącza logowanie hasłem.
* **Kopia bazy:** `python -m pmw_license backup-db --out kopia.db` (spójna kopia SQLite, uprawnienia 600). Przywrócenie: zatrzymaj
  serwer, podmień plik bazy, uruchom.
* Adres serwera licencji: tylko `https://` (wyjątek `http://127.0.0.1` / `localhost` do testów); przekierowania są odrzucane
  (`REDIRECT_REFUSED`), adres jest zapamiętany w tokenie klienta.

### Parowanie krok po kroku (OWNER)
1. Uruchom serwer (paczka `PepeMarketWizard_LICENSE_SERVER_1_29_0.zip`, `license_server/README.md`).
2. W aplikacji: **Licencje (OWNER)** → wpisz adres `https://…` → **Zapisz i sprawdź**.
3. Pojawi się kreator **jednorazowego parowania** z gotowym poleceniem `admin-keys add …` – wykonaj je w powłoce serwera (to jedyny krok
   poza aplikacją; klucz publiczny nie jest tajny).
4. **Sprawdź parowanie** → stan „Połączono – serwer ufa temu komputerowi”. Od tej chwili generowanie kluczy, lista, cofanie, reset urządzenia działają bez hasła.

### CLIENT
Klient wpisuje klucz w oknie **KEY FOR MAGIC**. Paczka CLIENT nie zawiera modułu OWNER (`owner.py`, `owner_key.py`), danych, baz ani
kluczy. Wersja CLIENT może być wydana **dopiero** z prawdziwym adresem HTTPS i zaufanym kluczem publicznym serwera (patrz §5).

---

## 3. Wykresy (§3)

* **„Wyznacz strefy” w głównym obszarze wykresów** (Precision → Wykresy MTF oraz Analiza AI): wybór **M1 + M5 + M15 (wszystkie trzy,
  domyślnie)**, pojedynczo M1 / M5 / M15, **M30**, albo M1 + M5 + M15 + M30; przełącznik **LIVE** (przeliczenie po zamknięciu świecy),
  **Zatrzymaj**, pasek postępu, błąd, **czas ostatniego udanego przeliczenia**, stan źródła każdego interwału (połączone / dane
  nieaktualne / brak danych / błąd). Strefy rysują się **tylko na wykresie tego samego instrumentu, symbolu brokera i interwału**;
  strefy innego symbolu nie są rysowane (komunikat). Przycisk wywołuje wyłącznie `/api/v1/market-zones/*` – nie otwiera pozycji i nie
  zmienia trybu ani ustawień handlu (sprawdzone testem: jedyne żądania POST to `/market-zones/…`, konfiguracja i tryb bez zmian).
* **Własne ustawienia każdego wykresu** (przycisk ⚙ na pasku wykresu, także na stronie Strefy rynkowe): kolory świec, knotów, tła,
  siatki i tekstu, rozmiar tekstu, siatka, wolumen, strefa czasu (jak na stronie / lokalna / UTC / serwera), widoczność, **kolor
  i krycie każdego typu strefy**, etykiety, „Przywróć domyślne”, **szablony** (zapisz / zastosuj / usuń). Przybliżenie, przesunięcie
  i automatyczna skala ceny – zapamiętane osobno dla wykresu (jak dotąd). Klucz zapisu: wykres + symbol + interwał – żadne dwa wykresy
  nie dzielą ustawień. Zapis lokalny w oknie aplikacji (WebView2 / przeglądarka), przywracany po ponownym uruchomieniu; uszkodzony
  zapis = ustawienia domyślne.
* **Menu „Warstwy”** na każdym wykresie: FVG, OB, popyt/podaż, wsparcie/opór, **płynność (hipoteza)**, etykiety. EQH/EQL to równe
  szczyty/dołki wyznaczone z OHLC – **hipoteza płynności, nie zmierzona płynność ani zlecenia oczekujące**.
* Strefa nieaktualna (brak danych / błąd / odtworzona po restarcie) jest szara i opisana „nieakt.”.

---

## 4. Jeden interfejs w stylu trzech wież (§2)

* **Motyw „trzy wieże”** (domyślny): granat, ametyst, szmaragd, złoto; kontrast tekstu sprawdzony (WCAG ≥ 4,5:1 dla tekstu). Dotychczasowy
  domyślny „złoty” zostaje na liście motywów; własne kolory użytkownika nie są nadpisywane (zmiana tylko, gdy był nietknięty domyślny).
* **Menu boczne według obszarów:** Menu – trzy wieże · **Precision** (wykresy i rynek) · **Dyscypline** (setupy i sygnały) ·
  **Profits** (wyniki i rachunek) · **Modele i trening** · **Ustawienia i diagnostyka** · **Licencje (OWNER)**. W wersji CLIENT obszaru
  Licencje nie ma, a stary link `#/licencje` prowadzi do Ustawień.
* **Stan widoczny na każdym ekranie** (pasek górny wszystkich trzech ram: zwykłej, wież i terminala): instrument i symbol brokera,
  MT5, **czas ostatnich danych**, **DEMO / LIVE / SYNTETYCZNE**, tryb wykonania, STOP, edycja OWNER / CLIENT i stan licencji.
* **Edycja w tytule okna:** „PepeMarketWizard OWNER – …” / „PepeMarketWizard CLIENT – …”; aplikacja Windows ma tytuł
  „PepeMarketWizard OWNER 1.29.0” (z `edition.json`; brak pliku = CLIENT, jak w silniku).
* 1280×720, 1920×1080, ekrany o wysokiej gęstości (2×), fokus klawiatury (widoczna ramka), `prefers-reduced-motion` (animacje
  i przejścia wyłączone) – sprawdzone testem w Chromium.

### Mapa ekranów: dotychczas → teraz (stare linki działają)
| Dotychczas | Link | Teraz |
|---|---|---|
| Pulpit (sekcja „Pulpit”) | `#/pulpit` | Precision → Pulpit |
| Neural Cyberpunk | `#/nc` | Precision → Neural Cyberpunk |
| Wykresy MTF | `#/wykresy` | Precision → Wykresy MTF (z „Wyznacz strefy”) |
| Strefy rynkowe | `#/strefy` | Precision → Strefy rynkowe |
| Scalping MTF / Kontekst / Indykatory / Analiza sygnału | `#/scalp-mtf` `#/kontekst` `#/indykatory` `#/sygnal` | Precision → te same zakładki |
| Setupy, Setup silnika, SCALPING/HEDGING, Analiza AI | `#/setupy` `#/warunki` `#/strategie` `#/ai` | Dyscypline → te same zakładki |
| Formacje | `#/formacje` | Dyscypline → Formacje i biblioteka |
| Pozycje i ryzyko, Dziennik | `#/pozycje` `#/dziennik` | Profits → te same zakładki |
| Modele, Centrum treningu, Neural, Structure, Testy | `#/modele` `#/trening` `#/neural` `#/struktura` `#/testy` | Modele i trening |
| Badania i walidacja | `#/badania` | Modele i trening → Badania i walidacja |
| Dane, Diagnostyka, Ustawienia | `#/dane` `#/diagnostyka` `#/ustawienia` | Ustawienia i diagnostyka |
| Licencje | `#/licencje` | Licencje (OWNER); w CLIENT ukryte → Ustawienia |
| Menu, Precision, Dyscypline, Profits | `#/menu` `#/precision` `#/dyscypline` `#/profits` | bez zmian |
| Trading Intelligence, AI Neural Lab, System Control | `#/trading-intelligence` `#/ai-neural-lab` `#/system-control` | bez zmian („Nowe panele”) |

Ta sama tabela jest w aplikacji: **Ustawienia → Mapa ekranów 1.29**.

---

## 5. Wydania (§5)

| Paczka | Zawartość | Stan |
|---|---|---|
| `PepeMarketWizard_OWNER_1_29_0.zip` | folder programu OWNER (bez Pythona) | budowana `tools/build_release.py` |
| `PepeMarketWizard_DESKTOP_OWNER_1_29_0.zip` | aplikacja Windows: EXE + wbudowany Python + program | `tools/build_desktop.py` |
| `PepeMarketWizard_LICENSE_SERVER_1_29_0.zip` | serwer licencji 1.1.0 (bez kluczy, bazy, `.env`) | `tools/build_release.py` |
| `PepeMarketWizard_DESKTOP_CLIENT_1_29_0.zip` | wersja dla klienta | **BLOKADA** – brak prawdziwego adresu HTTPS i klucza publicznego |

* **Build bez `.git`:** kopia bez historii git (np. „Download ZIP”) buduje się z jawnej listy plików `MANIFEST_SHA256.txt`; pliki spoza
  listy są wypisane (nie wchodzą do paczki); brak pliku z listy zatrzymuje build. Serwer licencji: z katalogu `license_server/`
  (bez danych, baz, `.env`, logów, kluczy) albo – gdy kopia go nie ma – pominięty z komunikatem.
* **Weryfikacja archiwów:** `python tools/verify_release.py --all` – ścieżki (ZIP-slip: brak `..`, ścieżek bezwzględnych, `\`,
  dowiązań), sumy z manifestów, brak plików zabronionych (dane, bazy, `.env`, klucze, klucz urządzenia OWNER), brak sekretów w tekście,
  zgodność `.sha256`, brak modułu OWNER w paczce CLIENT. Build uruchamia tę weryfikację automatycznie.
* **Podpis cyfrowy:** brak certyfikatu Authenticode – pliki **niepodpisane cyfrowo** (Windows SmartScreen może ostrzec).

### Jak wydać CLIENT (gdy serwer będzie gotowy)
1. Serwer licencji działa pod publicznym adresem `https://…` z ważnym certyfikatem TLS (reverse proxy) – `license_server/README.md`.
2. Na serwerze: `python -m pmw_license public-key` → zapisz klucz publiczny i `kid`.
3. Na komputerze OWNER, w folderze programu: `PRZYGOTUJ_PACZKE_KLIENTA.bat https://adres-serwera` (albo
   `python tools/stamp_client_edition.py --license-url https://adres-serwera --source release\PepeMarketWizard_DESKTOP_OWNER_1_29_0.zip`)
   – narzędzie pobiera klucz publiczny z serwera; **porównaj wyświetlony `kid` z wynikiem kroku 2**.
4. `python tools/verify_release.py <paczka CLIENT>` → OK.
5. Test na czystym Windows: start, KEY FOR MAGIC, aktywacja kluczem 72h, restart, brak sieci (nowe wejścia zablokowane, pozycje
   prowadzone).

---

## 6. Aktualizacja z 1.28 i powrót (rollback)

Sprawdzone narzędziem `python tools/migration_check.py` (git worktree 1.28.0 + kopie danych w katalogu tymczasowym): 15/15 PASS.
* 1.29 na kopii danych 1.28: wersja 1.29.0, konfiguracja zachowana (aktywa, mapowanie, port), wszystkie migracje bazy zachowane (bez
  nowych migracji bota w 1.29), strefy odtworzone (oznaczone jako nieaktualne do przeliczenia), adres serwera licencji z 1.28 zachowany,
  License Manager przechodzi na klucz urządzenia (bez hasła).
* Serwer licencji: baza v1 → v2 (tabele `admin_keys`, `admin_nonces`), licencje zachowane; `backup-db` działa.

**Procedura powrotu do 1.28:**
1. Zatrzymaj aplikację (STOP → zamknij aplikację; serwer: zatrzymaj usługę).
2. Aplikacja Windows: przed aktualizacją robi kopię danych w `%LOCALAPPDATA%\PepeMarketWizard\backups\` (pliki większe niż 128 MB –
   surowe eksporty – są tylko wymienione w manifeście kopii, nie kopiowane); przywróć folder `data\` z tej kopii (albo z własnej).
   Folder programu: rozpakuj paczkę 1.28 w miejsce 1.29.
3. Serwer: zatrzymaj, przywróć plik bazy z kopii `backup-db` sprzed aktualizacji, uruchom kod 1.0 (1.28). Sprawdzono też, że serwer
   1.28 pracuje na bazie v2 (nowe tabele pomija), ale **aplikacje OWNER 1.29 wymagają serwera 1.1** – po powrocie serwera do 1.0
   administracja z OWNER 1.29 nie zadziała (OWNER 1.28 – logowanie hasłem – tak, jeśli hasło jest ustawione).
4. Sprawdzone: 1.28 działa na kopii zapasowej sprzed aktualizacji; informacyjnie 1.28 uruchomił się też wprost na danych po 1.29.

---

## 7. Czego nie sprawdzono (BLOKADY i ograniczenia)

| Pozycja | Stan | Co trzeba zrobić |
|---|---|---|
| Paczka CLIENT | **BLOKADA** | publiczny serwer licencji `https://` + klucz publiczny → §5 „Jak wydać CLIENT” |
| Serwer licencji w internecie (TLS, proxy, domena) | nie sprawdzono | wdrożenie wg `license_server/README.md`, test z zewnątrz |
| Windows: DPAPI klucza OWNER, WebView2, tytuł okna, czysta instalacja | nie sprawdzono (Linux) | test na czystym Windows 10/11 |
| Prawdziwy MT5 (dane, czas serwera, koszty) | nie sprawdzono | test DEMO na Twoim terminalu |
| Podpis Authenticode | brak certyfikatu | certyfikat code-signing + `signtool` |
| Skuteczność stref / modeli / strategii | nie oceniano | dane syntetyczne nic nie mówią o rynku; brak dowodu przewagi |
| Lokalny Python | nie jest odporny na modyfikację | zdeterminowany użytkownik może zmienić kod u siebie; licencja chroni dostęp do serwera, nie kod |
