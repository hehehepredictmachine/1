"""Builds the two PDF manuals of release 1.29 (§6 of the update package):

  release/Instrukcja_Administrator_PepeMarketWizard.pdf   (OWNER)
  release/Instrukcja_Klient_PepeMarketWizard.pdf          (CLIENT)

  python tools/make_manuals.py [--shots data/logs] [--out release]

Layout of the manuals delivered with the package (header band, chapters "N / title", note and warning boxes, footer with the version),
text matching the 1.29 screens. Fonts: DejaVu Sans embedded (Polish characters). Screenshots (optional) come from the UI tests
(data/logs/ui_*), taken on the terminal SIMULATOR - every picture is captioned as synthetic data. Requires reportlab.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.29.0"
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("C:/Windows/Fonts"), ROOT / "build" / "fonts"]

DARK = colors.HexColor("#14261b")
GREEN = colors.HexColor("#1f6b45")
NOTE_BG, NOTE_LINE = colors.HexColor("#eef6f0"), colors.HexColor("#b9d8c4")
WARN_BG, WARN_LINE = colors.HexColor("#fff4e6"), colors.HexColor("#f0c890")
BLOCK_BG, BLOCK_LINE = colors.HexColor("#fdecec"), colors.HexColor("#e5a3a3")
GREY = colors.HexColor("#555b66")


def fonts() -> None:
    for d in FONT_DIRS:
        reg, bold = d / "DejaVuSans.ttf", d / "DejaVuSans-Bold.ttf"
        if reg.exists() and bold.exists():
            pdfmetrics.registerFont(TTFont("DejaVu", str(reg)))
            pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(bold)))
            pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu", boldItalic="DejaVu-Bold")
            from reportlab import rl_config
            rl_config.canvas_basefontname = "DejaVu"          # no unembedded Helvetica reference anywhere in the file
            return
    sys.exit("brak czcionek DejaVu Sans (DejaVuSans.ttf, DejaVuSans-Bold.ttf) – potrzebne do polskich znaków")


ST = {}


def styles() -> None:
    ST["title"] = ParagraphStyle("title", fontName="DejaVu-Bold", fontSize=27, leading=32, textColor=DARK, spaceAfter=10)
    ST["lead"] = ParagraphStyle("lead", fontName="DejaVu", fontSize=11.5, leading=16, textColor=GREY, spaceAfter=12)
    ST["h1"] = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=17, leading=22, textColor=DARK, spaceBefore=2, spaceAfter=8)
    ST["h2"] = ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=11.5, leading=15, textColor=GREEN, spaceBefore=8, spaceAfter=4)
    ST["p"] = ParagraphStyle("p", fontName="DejaVu", fontSize=9.6, leading=13.6, textColor=colors.black, spaceAfter=5, alignment=TA_LEFT,
                             bulletFontName="DejaVu")
    ST["li"] = ParagraphStyle("li", parent=ST["p"], spaceAfter=3)
    ST["box"] = ParagraphStyle("box", parent=ST["p"], fontSize=9.2, leading=13, spaceAfter=0)
    ST["cap"] = ParagraphStyle("cap", parent=ST["p"], fontSize=8, leading=10.5, textColor=GREY, spaceAfter=8)
    ST["cell"] = ParagraphStyle("cell", parent=ST["p"], fontSize=8.4, leading=11, spaceAfter=0)
    ST["cellb"] = ParagraphStyle("cellb", parent=ST["cell"], fontName="DejaVu-Bold")


def P(text: str, st: str = "p") -> Paragraph:
    return Paragraph(text, ST[st])


def bullets(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(P(t, "li"), leftIndent=12, value="•", bulletFontName="DejaVu") for t in items], bulletType="bullet", start="•",
                        leftIndent=12, bulletFontName="DejaVu", bulletFontSize=9)


def steps(items: list[str]) -> ListFlowable:
    return ListFlowable([ListItem(P(t, "li"), leftIndent=16, bulletFontName="DejaVu-Bold") for t in items], bulletType="1", leftIndent=16,
                        bulletFontName="DejaVu-Bold",
                        bulletFontSize=9, bulletFormat="%s.")


def box(text: str, kind: str = "note") -> Table:
    bg, line = {"note": (NOTE_BG, NOTE_LINE), "warn": (WARN_BG, WARN_LINE), "block": (BLOCK_BG, BLOCK_LINE)}[kind]
    t = Table([[P(text, "box")]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 0.8, line),
                           ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([Spacer(1, 4), t, Spacer(1, 6)])


def table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[P(c, "cellb" if i == 0 else "cell") for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "DejaVu"), ("BACKGROUND", (0, 0), (-1, 0), NOTE_BG), ("GRID", (0, 0), (-1, -1), 0.4, NOTE_LINE),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                           ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
    return t


def shot(shots: Path | None, rel: str, caption: str, width_mm: float = 170, crop: tuple | None = None) -> list:
    """Screenshot from the UI tests (simulator) with a caption; skipped when not available."""
    if not shots:
        return []
    p = shots / rel
    if not p.exists():
        return []
    src = p
    if crop:
        from PIL import Image as PILImage
        im = PILImage.open(p)
        w, h = im.size
        box_ = (int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h))
        tmp = Path(ROOT / "build" / "manual_img")
        tmp.mkdir(parents=True, exist_ok=True)
        src = tmp / (p.stem + f"_{abs(hash(crop)) % 10**6}.png")
        im.crop(box_).save(src)
    from PIL import Image as PILImage
    w, h = PILImage.open(src).size
    width = width_mm * mm
    return [KeepTogether([Image(str(src), width=width, height=width * h / w), P(caption + " <i>(symulator – dane syntetyczne)</i>", "cap")])]


def page_deco(role: str):
    def deco(c, doc):
        w, h = A4
        c.saveState()
        c.setFillColor(DARK)
        c.rect(0, h - 15 * mm, w, 15 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("DejaVu-Bold", 8.5)
        c.drawString(18 * mm, h - 9.4 * mm, "PEPEMARKETWIZARD")
        c.setFont("DejaVu", 7.5)
        c.drawRightString(w - 18 * mm, h - 9.4 * mm, role)
        c.setStrokeColor(NOTE_LINE)
        c.setLineWidth(0.6)
        c.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)
        c.setFillColor(GREY)
        c.setFont("DejaVu", 7)
        c.drawString(18 * mm, 9.5 * mm, f"INSTRUKCJA • WERSJA {VERSION} • {role}")
        c.drawRightString(w - 18 * mm, 9.5 * mm, str(doc.page))
        c.restoreState()
    return deco


def build(path: Path, role: str, story: list, title: str) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=24 * mm, bottomMargin=20 * mm,
                            title=title, author="PepeMarketWizard", subject=f"PepeMarketWizard {VERSION}", creator="tools/make_manuals.py",
                            initialFontName="DejaVu", initialFontSize=9)
    deco = page_deco(role)
    doc.build(story, onFirstPage=deco, onLaterPages=deco)


# ---------------------------------------------------------------------------------------------------------------- administrator
def admin(shots: Path | None) -> list:
    s: list = [Spacer(1, 18 * mm), P("Instrukcja<br/>administratora", "title"),
               P("Obsługa bota PepeMarketWizard w wersji OWNER 1.29: uruchomienie, interfejs trzech wież, wykresy i strefy, trening, "
                 "serwer licencji bez logowania, wydawanie wersji klienta, aktualizacja i powrót.", "lead"),
               box("<b>Stan:</b> instrukcja odpowiada wersji <b>1.29.0</b> (OWNER). Opisane ekrany i polecenia zostały uruchomione "
                   "i sprawdzone testami w Chromium na symulatorze terminala. Elementy, których nie dało się sprawdzić, są oznaczone "
                   "jako <b>BLOKADA</b> lub „nie sprawdzono”."),
               P("Co znajdziesz w instrukcji", "h2"),
               bullets(["Uruchomienie aplikacji i połączenie z MT5.", "Menu według obszarów wież i pasek stanu.",
                        "Wykresy: „Wyznacz strefy”, własne ustawienia wykresu, warstwy.", "Eksport danych i trening modeli.",
                        "Serwer licencji 1.1 i parowanie komputera OWNER (bez hasła).",
                        "Licencje dla klientów, wersja CLIENT (BLOKADA do czasu uruchomienia serwera).",
                        "Aktualizacja z 1.28, kopia i powrót, typowe problemy."]),
               box("Nie przeprowadzono tutaj testu na Twoim Windows ani połączenia z prawdziwym MT5 i publicznym serwerem licencji. "
                   "Zrzuty ekranu pochodzą z symulatora (dane syntetyczne). Sprawdź działanie na rachunku DEMO, zanim użyjesz AUTO LIVE.", "warn"),
               PageBreak()]
    # 1
    s += [P("1 / Pierwsze uruchomienie", "h1"), P("Przygotowanie", "h2"),
          bullets(["Rozpakuj paczkę <b>PepeMarketWizard_DESKTOP_OWNER_1_29_0.zip</b> do nowego folderu (nie nadpisuj starej wersji). "
                   "Zachowaj kopię danych sprzed aktualizacji (rozdział 8).",
                   "Uruchom MT5 i zaloguj się do właściwego rachunku. Symbol brokera (np. <b>XAUUSD-</b>) musi być widoczny w Market Watch.",
                   "Windows potrzebuje WebView2. Pierwszy start instaluje zależności z Internetu (lub z paczki OFFLINE)."]),
          P("Start aplikacji", "h2"),
          P("Uruchom <b>PepeMarketWizardDesktop.exe</b>. Tytuł okna to <b>PepeMarketWizard OWNER 1.29.0</b> – oznaczenie edycji "
            "widać też na pasku zadań i w zakładce panelu. Przy problemie uruchom <b>02_DIAGNOSTYKA.bat</b> i zachowaj wynik."),
          P("Dane aplikacji Windows: <b>%LOCALAPPDATA%\\PepeMarketWizard\\data</b> (tryb portable: folder programu). Kopie sprzed "
            "aktualizacji: <b>%LOCALAPPDATA%\\PepeMarketWizard\\backups</b>."),
          box("Pliki EXE nie są podpisane cyfrowo (brak certyfikatu Authenticode) – Windows SmartScreen może pokazać ostrzeżenie. "
              "Uruchamiaj tylko paczkę, której sumę SHA-256 porównałeś z plikiem .sha256 / raportem.", "warn"),
          PageBreak()]
    # 2
    s += [P("2 / Interfejs: obszary trzech wież i pasek stanu", "h1"),
          P("Menu boczne jest ułożone według obszarów menu głównego. Kliknięcie obszaru otwiera jego pierwszą zakładkę; pozostałe są "
            "na pasku zakładek nad stroną."),
          table([["Obszar", "Zawartość"],
                 ["Menu – trzy wieże", "menu główne z wieżami (logo w lewym górnym rogu również tu prowadzi)"],
                 ["Precision", "Pulpit, Wykresy MTF, Strefy rynkowe, Scalping MTF, Kontekst rynku, Indykatory, Analiza sygnału, Neural Cyberpunk"],
                 ["Dyscypline", "Scenariusze, Setup silnika S01–S12, SCALPING / HEDGING, Analiza AI, Formacje"],
                 ["Profits", "Pozycje i ryzyko, Dziennik i wyniki, widok Profits"],
                 ["Modele i trening", "Modele, Centrum treningu, Neural System, Structure Intelligence, Testy, Badania i walidacja"],
                 ["Ustawienia i diagnostyka", "Ustawienia (z mapą ekranów), Dane i źródła, Diagnostyka"],
                 ["Licencje (OWNER)", "License Manager – tylko w wersji OWNER"]], [45, 125]),
          P("Pasek stanu (każdy ekran)", "h2"),
          P("U góry każdego ekranu (zwykłego, wież i terminala): instrument i symbol brokera, MT5, jakość i <b>czas ostatnich danych</b>, "
            "rodzaj danych <b>DEMO / LIVE / SYNTETYCZNE</b>, tryb wykonania, STOP oraz <b>OWNER</b> / CLIENT i stan licencji."),
          *shot(shots, "ui_interface_129/01_owner_appshell_1920.png", "Pasek stanu i menu obszarów.", crop=(0, 0, 1, 0.42)),
          P("Gdzie są dawne zakładki? <b>Ustawienia i diagnostyka → Ustawienia → Mapa ekranów 1.29</b>. Dotychczasowe linki "
            "(np. #/wykresy, #/ai, #/warunki/…) działają bez zmian."),
          PageBreak()]
    # 3
    s += [P("3 / Wykresy i strefy", "h1"), P("Wyznacz strefy w głównym obszarze wykresów", "h2"),
          steps(["Otwórz <b>Precision → Wykresy MTF</b> (albo Analiza AI). Nad wykresami jest pasek <b>Strefy XAUUSD</b> / BTC.",
                 "Wybierz zakres: <b>M1 + M5 + M15 (wszystkie trzy)</b> – domyślnie, albo pojedynczo M1, M5, M15, M30, albo wszystkie cztery.",
                 "Kliknij <b>Wyznacz strefy</b>. Widać postęp, czas ostatniego udanego przeliczenia i stan źródła każdego interwału "
                 "(połączone / dane nieaktualne / brak danych / błąd). Wielokrotne kliknięcie nie uruchamia kilku zadań.",
                 "<b>LIVE</b> przelicza strefy po zamknięciu każdej świecy wybranych interwałów; <b>Zatrzymaj</b> kończy."]),
          *shot(shots, "ui_chart_prefs/01_bot_charts_zones.png", "Pasek „Wyznacz strefy” nad wykresami.", crop=(0.13, 0.31, 1, 0.48)),
          P("Strefy rysują się wyłącznie na wykresie tego samego instrumentu, symbolu brokera i interwału. Strefa nieaktualna jest szara "
            "z dopiskiem „nieakt.”. Analiza stref nie otwiera pozycji i nie zmienia trybu ani ustawień handlu."),
          P("Ustawienia wykresu i warstwy", "h2"),
          bullets(["Przycisk <b>⚙</b> na pasku wykresu: kolory świec, knotów, tła, siatki i tekstu; rozmiar tekstu; siatka; wolumen; strefa "
                   "czasu; kolor i krycie każdego typu strefy; etykiety; <b>szablony</b> i <b>Przywróć domyślne</b>.",
                   "Ustawienia są zapisane dla danego wykresu (instrument + interwał) i wracają po ponownym uruchomieniu.",
                   "<b>Warstwy</b>: FVG, OB, popyt/podaż, wsparcie/opór, płynność (hipoteza), etykiety.",
                   "Przybliżenie, przesunięcie i automatyczna skala ceny (przyciski +, −, Dopasuj, A) są zapamiętywane osobno dla wykresu."]),
          *shot(shots, "ui_chart_prefs/03_settings_dialog.png", "Okno „Ustawienia wykresu”.", width_mm=140, crop=(0.22, 0.13, 0.78, 0.87)),
          box("EQH/EQL to równe szczyty i dołki wyznaczone z OHLC – <b>hipoteza</b> płynności, nie zmierzona płynność ani zlecenia "
              "oczekujące. Wynik jakości strefy 0–100 nie jest prawdopodobieństwem.", "warn"),
          PageBreak()]
    # 4
    s += [P("4 / Eksport danych i trening modeli", "h1"), P("Centrum treningu (Modele i trening → Centrum treningu)", "h2"),
          steps(["Połącz MT5, sprawdź symbol i dostępność historii u brokera.",
                 "Wybierz XAUUSD albo BTC – instrumenty trenuj i oceniaj osobno.",
                 "<b>Eksportuj dane</b> (przyrostowo). Sprawdź okres, interwały, liczbę świec, luki i raport jakości.",
                 "<b>Przygotuj dataset</b>, <b>Trenuj</b> albo <b>Uruchom cały proces</b>. Postęp, log i anulowanie są w panelu.",
                 "Porównaj wersje z modelem bazowym: walidacja czasowa (purging, embargo), zbiór końcowy nieużyty do strojenia, koszty.",
                 "<b>Aktywuj</b> tylko po teście zgodności i predykcji; <b>Rollback</b> cofa aktywację."]),
          P("Bez bota: <b>32_CENTRUM_TRENINGU.bat</b>."),
          box("Wytrenowany model nie jest dowodem przewagi. Nowe modele działają w trybie OBSERVATION (nie głosują w strategiach). "
              "Wynik na danych syntetycznych nic nie mówi o rynku.", "warn"),
          PageBreak()]
    # 5
    s += [P("5 / Serwer licencji 1.1", "h1"),
          P("Serwer licencji to osobna usługa na Twoim serwerze (nie na komputerze z botem): paczka "
            "<b>PepeMarketWizard_LICENSE_SERVER_1_29_0.zip</b>, opis w <b>license_server/README.md</b>."),
          P("Instalacja (powłoka serwera)", "h2"),
          steps(["Python 3.11+ i wirtualne środowisko w folderze usługi; <b>pip install -r requirements.txt</b>.",
                 "<b>python -m pmw_license init-keys</b> – klucz podpisu (zostaje na serwerze); zapisz wypisany klucz PUBLICZNY i kid.",
                 "<b>python -m pmw_license new-pepper</b> – wpisz wynik do pliku <b>.env</b> (wzór: .env.example). Hasło administratora "
                 "nie jest potrzebne (pole może zostać puste).",
                 "Uruchom <b>python -m pmw_license serve</b> jako usługę za reverse proxy z HTTPS (ważny certyfikat, własna domena).",
                 "Kopia bazy: <b>python -m pmw_license backup-db --out kopia.db</b> (regularnie, poza serwerem)."]),
          box("Nie wysyłaj nikomu klucza prywatnego podpisu, pliku bazy ani .env. Nie wystawiaj panelu bez HTTPS. "
              "Adres serwera w aplikacji musi zaczynać się od https:// (wyjątek: 127.0.0.1 do testów).", "warn"),
          box("<b>Nie sprawdzono:</b> wdrożenia w Internecie (domena, TLS, proxy). Testy objęły serwer uruchomiony lokalnie "
              "(aktywacja, cofnięcie, wygaśnięcie, brak sieci, restart, powtórzenie żądania, kopia i odtworzenie).", "block"),
          PageBreak()]
    # 6
    s += [P("6 / Licencje (OWNER) – parowanie i obsługa", "h1"), P("Jednorazowe parowanie (bez hasła)", "h2"),
          steps(["W aplikacji otwórz <b>Licencje (OWNER)</b>, wpisz adres <b>https://…</b> i kliknij <b>Zapisz i sprawdź</b>.",
                 "Kreator pokaże polecenie <b>python -m pmw_license admin-keys add --public-key … --label \"OWNER …\"</b> z kluczem "
                 "publicznym tego komputera. Wykonaj je w powłoce serwera (SSH).",
                 "Kliknij <b>Sprawdź parowanie</b> – stan „Połączono – serwer ufa temu komputerowi”."]),
          *shot(shots, "ui_license/05a_owner_pairing.png", "Kreator parowania w License Manager.", width_mm=150),
          P("Klucz prywatny komputera jest zaszyfrowany Windows DPAPI i nie opuszcza komputera. Każde żądanie jest podpisane (czas, "
            "jednorazowy nonce); serwer odrzuca powtórzenia także po restarcie."),
          P("Klucze dla klientów", "h2"),
          bullets(["Wybierz <b>72 godziny</b>, <b>7 dni</b> albo <b>31 dni</b> (24 godziny: „zaawansowane”), dodaj notatkę i utwórz klucz. "
                   "Pełny klucz jest pokazany <b>tylko raz</b> – skopiuj go dla klienta.",
                   "Czas licencji liczy się od pierwszej aktywacji. Lista pokazuje stan, urządzenie i wygaśnięcie.",
                   "<b>Cofnij</b> – licencja przestaje działać. <b>Reset urządzenia</b> – klient może aktywować na innym komputerze; "
                   "reset nie wydłuża licencji."]),
          P("Rotacja i utrata komputera", "h2"),
          bullets(["Rotacja: <b>Rozpocznij rotację klucza</b> → dodaj nowy klucz poleceniem z kreatora → <b>Zakończ rotację</b> "
                   "(stary klucz zostaje odwołany).",
                   "Utrata komputera: na serwerze <b>admin-keys list</b>, potem <b>admin-keys revoke &lt;kid&gt; --reason \"utracony\"</b>; "
                   "nowy komputer sparuj od nowa."]),
          PageBreak()]
    # 7
    s += [P("7 / Wersja dla klienta (CLIENT)", "h1"),
          box("<b>BLOKADA:</b> paczka <b>PepeMarketWizard_DESKTOP_CLIENT_1_29_0.zip</b> nie została wydana – nie ma jeszcze "
              "publicznego adresu HTTPS serwera licencji ani jego zaufanego klucza publicznego. Paczka z przykładowym adresem byłaby "
              "bezużyteczna i niebezpieczna.", "block"),
          P("Jak wydać, gdy serwer działa", "h2"),
          steps(["Na serwerze: <b>python -m pmw_license public-key</b> – zapisz klucz publiczny i kid.",
                 "Na komputerze OWNER, w folderze programu: <b>PRZYGOTUJ_PACZKE_KLIENTA.bat https://adres-serwera</b> "
                 "(albo tools\\stamp_client_edition.py). Porównaj wyświetlony kid z krokiem 1.",
                 "Sprawdź paczkę: <b>python tools\\verify_release.py &lt;paczka&gt;</b> – ścieżki, sumy, brak plików i modułów OWNER.",
                 "Przetestuj na czystym Windows: start, KEY FOR MAGIC, aktywacja, restart, brak sieci.",
                 "Przekaż klientowi paczkę, klucz i <b>Instrukcję klienta</b>."]),
          P("Paczka CLIENT nie zawiera License Managera, klucza urządzenia OWNER, Twoich danych, baz ani kluczy. W CLIENT nie ma obszaru "
            "Licencje; tytuł okna to „PepeMarketWizard CLIENT 1.29.0”."),
          box("Brak licencji lub połączenia u klienta blokuje <b>nowe wejścia</b>. Otwarte pozycje nie są zamykane – SL/TP, częściowe "
              "zamknięcia i hedging działają dalej. Lokalny program nie jest odporny na modyfikację przez zdeterminowanego użytkownika."),
          PageBreak()]
    # 8
    s += [P("8 / Aktualizacja z 1.28, kopia i powrót", "h1"),
          P("Aktualizację i powrót sprawdzono na kopiach danych (narzędzie <b>tools/migration_check.py</b>): 1.29 uruchamia się na danych "
            "1.28, zachowuje konfigurację, migracje bazy, strefy i adres serwera licencji; serwer licencji przechodzi z bazy v1 na v2 "
            "bez utraty licencji."),
          P("Aktualizacja", "h2"),
          steps(["Zatrzymaj aplikację (STOP nowych wejść → zamknij). Zapisz kopię folderu danych.",
                 "Serwer: <b>backup-db</b>, zatrzymaj usługę, podmień pliki programu na 1.1.0, uruchom (baza przechodzi na v2 sama).",
                 "Rozpakuj OWNER 1.29 do nowego folderu i uruchom; aplikacja Windows sama robi kopię danych przed migracją.",
                 "Licencje (OWNER): <b>Zapisz i sprawdź</b> → sparuj komputer (rozdział 6)."]),
          P("Powrót do 1.28", "h2"),
          steps(["Zatrzymaj 1.29. Przywróć folder <b>data</b> z kopii sprzed aktualizacji (backups).",
                 "Uruchom program 1.28 z jego folderu.",
                 "Serwer: przywróć bazę z kopii sprzed aktualizacji i uruchom kod 1.0. Uwaga: aplikacja OWNER 1.29 wymaga serwera 1.1."]),
          P("9 / Typowe problemy", "h1"),
          table([["Objaw", "Co zrobić"],
                 ["MT5 rozłączony / dane nieaktualne", "uruchom terminal, sprawdź logowanie, symbol, historię i 02_DIAGNOSTYKA.bat"],
                 ["Brak stref", "wybierz zakres, sprawdź stan źródła i czas danych, kliknij Wyznacz strefy, odczytaj błąd"],
                 ["Licencje: „klucz nie jest zaufany”", "komputer nie jest sparowany – wykonaj polecenie admin-keys add z kreatora"],
                 ["Licencje: „czas żądania”", "zegar komputera i serwera różnią się o ponad 2 minuty – włącz synchronizację czasu"],
                 ["Licencje: przekierowanie odrzucone", "podaj ostateczny adres https:// serwera (bez przekierowań)"],
                 ["Trening pominięty", "sprawdź log zadania, zakres historii, luki, RAM i wymagania modelu"]], [60, 110]),
          box("Nie dołączaj do zgłoszeń haseł, tokenów, pełnych kluczy licencyjnych, kluczy prywatnych ani plików bazy. "
              "Wyniki testów: release/RAPORT_KONCOWY.md (PASS / FAIL / BLOCKED).", "warn")]
    return s


# ---------------------------------------------------------------------------------------------------------------- client
def client(shots: Path | None) -> list:
    s: list = [Spacer(1, 18 * mm), P("Instrukcja<br/>klienta", "title"),
               P("Instalacja, aktywacja licencji, połączenie z MT5 i korzystanie z PepeMarketWizard w wersji CLIENT 1.29.", "lead"),
               box("<b>Stan:</b> paczkę CLIENT przygotowuje właściciel po uruchomieniu serwera licencji. Ekrany opisane tutaj "
                   "sprawdzono w wersji 1.29 na symulatorze; jeśli Twoja paczka wygląda inaczej, zapytaj właściciela o aktualną wersję."),
               P("Co przygotować", "h2"),
               bullets(["Komputer z Windows 10/11 i połączeniem z Internetem.",
                        "Paczkę <b>CLIENT</b> i klucz licencyjny od właściciela.",
                        "Terminal MetaTrader 5 z dostępem do własnego rachunku."]),
               box("Nie wysyłaj nikomu hasła do MT5 ani kodów bezpieczeństwa. Pełny klucz licencji traktuj jak prywatny kod dostępu.", "warn"),
               PageBreak()]
    s += [P("1 / Instalacja i aktywacja", "h1"), P("Pierwsze uruchomienie", "h2"),
          steps(["Rozpakuj całą paczkę CLIENT do nowego folderu. Nie uruchamiaj programu z wnętrza ZIP-a.",
                 "Uruchom <b>PepeMarketWizardDesktop.exe</b>. Tytuł okna: <b>PepeMarketWizard CLIENT 1.29.0</b>. Pierwszy start "
                 "pobiera wymagane składniki.",
                 "W oknie <b>KEY FOR MAGIC</b> wklej klucz i kliknij aktywację. Program łączy się z serwerem licencji właściciela.",
                 "Sprawdź komunikat i datę wygaśnięcia (widoczną też na pasku u góry: „CLIENT · licencja do …”)."]),
          *shot(shots, "ui_license/01_key_for_magic.png", "Okno KEY FOR MAGIC.", width_mm=150),
          P("Ważność", "h2"),
          P("Licencja trwa <b>72 godziny</b>, <b>7 dni</b> albo <b>31 dni</b> od pierwszej aktywacji i jest przypisana do komputera. "
            "Przed zmianą komputera poproś właściciela o reset urządzenia."),
          box("Bez ważnej licencji lub bez połączenia z serwerem program <b>nie otwiera nowych pozycji</b>. Otwarte pozycje nie są "
              "zamykane – SL/TP i prowadzenie pozycji działają dalej. Otwarte pozycje sprawdzaj także w MT5."),
          PageBreak()]
    s += [P("2 / Połączenie z MT5", "h1"),
          steps(["Uruchom MetaTrader 5 i zaloguj się na właściwy rachunek. Dane logowania wpisuj tylko w polach do tego przeznaczonych.",
                 "W Market Watch sprawdź dokładną nazwę instrumentu (np. <b>XAUUSD-</b>; zależy od brokera).",
                 "W <b>Ustawienia i diagnostyka → Ustawienia</b> sprawdź symbol i mapowanie BTC.",
                 "Ustaw znane koszty (prowizja) i limity ryzyka zgodnie z rachunkiem."]),
          P("Jak czytać pasek stanu", "h2"),
          table([["Element", "Znaczenie"],
                 ["XAUUSD / BTC i symbol", "instrument i symbol brokera, na którym pracuje bot"],
                 ["MT5 połączony / rozłączony", "stan terminala według programu"],
                 ["Ostatnie dane", "czas ostatniego notowania z MT5 – jeśli stary, wykres nie pokazuje bieżącego rynku"],
                 ["DEMO / LIVE / SYNTETYCZNE", "rodzaj rachunku potwierdzony przez terminal; SYNTETYCZNE = symulator, nie Twój rachunek"],
                 ["Tryb, STOP", "SIGNALS / PAPER / AUTO DEMO / AUTO LIVE; STOP zatrzymuje nowe wejścia"],
                 ["CLIENT · licencja", "stan licencji i data wygaśnięcia"]], [55, 115]),
          PageBreak()]
    s += [P("3 / Korzystanie z panelu", "h1"),
          P("Menu jest ułożone jak trzy wieże: <b>Precision</b> (wykresy i rynek), <b>Dyscypline</b> (setupy i sygnały), <b>Profits</b> "
            "(rachunek i wyniki), oraz <b>Modele i trening</b> i <b>Ustawienia i diagnostyka</b>. Logo prowadzi do menu głównego."),
          P("Strefy na wykresie", "h2"),
          steps(["Otwórz <b>Precision → Wykresy MTF</b>.",
                 "Na pasku <b>Strefy</b> wybierz M1 + M5 + M15 (domyślnie) albo pojedynczy interwał; M30 też jest dostępny.",
                 "Kliknij <b>Wyznacz strefy</b>. <b>LIVE</b> przelicza strefy po zamknięciu kolejnej świecy.",
                 "Szczegóły stref (checklista, historia): <b>Precision → Strefy rynkowe</b>."]),
          P("Własne ustawienia wykresu", "h2"),
          bullets(["<b>⚙</b> na pasku wykresu: kolory, siatka, rozmiar tekstu, wolumen, strefa czasu, kolor i krycie stref, szablony, "
                   "„Przywróć domyślne”. Ustawienia każdego wykresu są pamiętane po ponownym uruchomieniu.",
                   "<b>Warstwy</b>: pokaż / ukryj FVG, OB, popyt/podaż, wsparcie/opór, płynność (hipoteza) i etykiety."]),
          box("Strefy to informacja analityczna – przycisk nie otwiera pozycji i nie zmienia ustawień handlu. Płynność EQH/EQL to "
              "hipoteza wyznaczona z OHLC, nie zmierzone zlecenia.", "warn"),
          PageBreak()]
    s += [P("4 / Tryby, licencja i pomoc", "h1"), P("Tryb pracy", "h2"),
          P("<b>SIGNALS</b> – analiza bez nowych zleceń. <b>PAPER</b> – symulacja. <b>AUTO DEMO</b> i <b>AUTO LIVE</b> – zlecenia na "
            "odpowiednim rachunku, z potwierdzeniem. Zacznij od SIGNALS lub PAPER i rachunku DEMO."),
          P("Rozwiązywanie problemów", "h2"),
          table([["Objaw", "Co zrobić"],
                 ["Nie mogę aktywować", "sprawdź Internet, treść klucza i czas systemowy; licencja mogła wygasnąć lub być przypisana do "
                  "innego komputera – skontaktuj się z właścicielem"],
                 ["„brak połączenia z serwerem licencji”", "sprawdź Internet; nowe wejścia są wstrzymane, otwarte pozycje prowadzone"],
                 ["Brak wykresu", "uruchom MT5, sprawdź symbol, historię i stan połączenia"],
                 ["Brak stref", "wybierz interwały, sprawdź czas danych i stan źródła, kliknij Wyznacz strefy"]], [55, 115]),
          box("Wyniki historyczne i wyniki modeli nie gwarantują przyszłych wyników. Nie przekazuj nikomu haseł ani pełnych danych "
              "dostępowych; zgłaszając problem, podaj treść komunikatu bez pełnego klucza.", "warn")]
    return s


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "data" / "logs"), help="folder ze zrzutami testów UI (opcjonalnie)")
    ap.add_argument("--out", default=str(ROOT / "release"))
    a = ap.parse_args()
    fonts()
    styles()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    shots = Path(a.shots) if Path(a.shots).is_dir() else None
    build(out / "Instrukcja_Administrator_PepeMarketWizard.pdf", "ADMINISTRATOR", admin(shots), "PepeMarketWizard – instrukcja administratora")
    build(out / "Instrukcja_Klient_PepeMarketWizard.pdf", "KLIENT", client(shots), "PepeMarketWizard – instrukcja klienta")
    for n in ("Instrukcja_Administrator_PepeMarketWizard.pdf", "Instrukcja_Klient_PepeMarketWizard.pdf"):
        print(f"{n}: {(out / n).stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
