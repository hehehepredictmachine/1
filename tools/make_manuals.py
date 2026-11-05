"""Builds the two PDF manuals (§6 of the update package; 1.30: without the removed license system):

  release/Instrukcja_Administrator_PepeMarketWizard.pdf   (administrator / owner of the bot)
  release/Instrukcja_Klient_PepeMarketWizard.pdf          (user)

  python tools/make_manuals.py [--shots data/logs] [--out release]

Layout of the manuals delivered with the package (header band, chapters "N / title", note and warning boxes, footer with the version),
text matching the 1.30 screens. Fonts: DejaVu Sans embedded (Polish characters). Screenshots (optional) come from the UI tests
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
VERSION = "1.32.0"
TAG = VERSION.replace(".", "_")
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
    im = PILImage.open(src)
    if im.width > 1400 or p.stat().st_size > 400_000:   # artwork screenshots (1.32): embedded as a smaller JPEG, not a multi-MB PNG
        tmp = Path(ROOT / "build" / "manual_img")
        tmp.mkdir(parents=True, exist_ok=True)
        im = im.convert("RGB")
        if im.width > 1400:
            im = im.resize((1400, round(im.height * 1400 / im.width)), PILImage.LANCZOS)
        src = tmp / (src.stem + "_s.jpg")
        im.save(src, quality=84, optimize=True)
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
               P("Obsługa bota PepeMarketWizard 1.32: uruchomienie (launcher JOIN THE CULT), menu główne – miasto sześciu wież, "
                 "panele Lightning / Wind / Control / Strategy Lab, wykresy i strefy, trening modeli, wydawanie paczek, aktualizacja "
                 "i powrót.", "lead"),
               box("<b>Stan:</b> instrukcja odpowiada wersji <b>" + VERSION + "</b>. Opisane ekrany i polecenia zostały uruchomione "
                   "i sprawdzone testami w Chromium na symulatorze terminala. Czego nie dało się sprawdzić – oznaczono "
                   "„nie sprawdzono”. <b>System licencji został usunięty</b> (na Twoją prośbę): program działa bez klucza, "
                   "nie ma License Managera, okna KEY FOR MAGIC, wersji CLIENT ani serwera licencji."),
               P("Co znajdziesz w instrukcji", "h2"),
               bullets(["Uruchomienie aplikacji (launcher JOIN THE CULT) i połączenie z MT5.",
                        "Menu główne (sześć wież), panele Lightning / Wind / Control / Strategy Lab, menu boczne i pasek stanu.",
                        "Wykresy: „Wyznacz strefy”, własne ustawienia wykresu, warstwy.", "Eksport danych i trening modeli.",
                        "Paczki do przekazania innym osobom (bez licencji).", "Aktualizacja z 1.29, kopia i powrót, typowe problemy."]),
               box("Nie przeprowadzono tutaj testu na Twoim Windows ani połączenia z prawdziwym MT5. Zrzuty ekranu pochodzą "
                   "z symulatora (dane syntetyczne). Sprawdź działanie na rachunku DEMO, zanim użyjesz AUTO LIVE.", "warn"),
               PageBreak()]
    # 1
    s += [P("1 / Pierwsze uruchomienie", "h1"), P("Przygotowanie", "h2"),
          bullets(["Rozpakuj paczkę <b>PepeMarketWizard_DESKTOP_" + TAG + ".zip</b> do nowego folderu (nie nadpisuj starej wersji). "
                   "Zachowaj kopię danych sprzed aktualizacji (rozdział 6).",
                   "Uruchom MT5 i zaloguj się do właściwego rachunku. Symbol brokera (np. <b>XAUUSD-</b>) musi być widoczny w Market Watch.",
                   "Windows potrzebuje WebView2. Pierwszy start instaluje zależności z Internetu (lub z paczki OFFLINE)."]),
          P("Start aplikacji", "h2"),
          P("Uruchom <b>PepeMarketWizardDesktop.exe</b> (tytuł okna: <b>PepeMarketWizard " + VERSION + "</b>). Klucz licencji nie jest potrzebny. "
            "Przy problemie uruchom <b>02_DIAGNOSTYKA.bat</b> i zachowaj wynik."),
          P("Najpierw otwiera się małe okno <b>JOIN THE CULT</b> (launcher): pokazuje postęp pierwszego startu, wybór danych poprzedniej "
            "instalacji albo błąd z przyciskami <b>Spróbuj ponownie</b>, <b>Otwórz folder logów</b> i <b>Zamknij</b>. Gdy silnik działa, "
            "launcher pokazuje <b>SYSTEM READY</b> – bot pracuje już w tle. <b>JOIN THE CULT</b> powiększa okno do 85 % ekranu i otwiera "
            "menu główne z 6-sekundowym intro (<b>Pomiń intro</b> albo Esc; przy ograniczonych animacjach systemu intro jest pomijane). "
            "W przeglądarce (bez aplikacji Windows) ten sam launcher pojawia się na początku sesji."),
          *shot(shots, "ui_cult/01_launcher_1920.png", "Launcher JOIN THE CULT – SYSTEM READY.", width_mm=150),
          P("Dane aplikacji Windows: <b>%LOCALAPPDATA%\\PepeMarketWizard\\data</b> (tryb portable: folder programu). Kopie sprzed "
            "aktualizacji: <b>%LOCALAPPDATA%\\PepeMarketWizard\\backups</b>."),
          box("Pliki EXE nie są podpisane cyfrowo (brak certyfikatu Authenticode) – Windows SmartScreen może pokazać ostrzeżenie. "
              "Uruchamiaj tylko paczkę, której sumę SHA-256 porównałeś z plikiem .sha256 / raportem.", "warn"),
          PageBreak()]
    # 2
    s += [P("2 / Interfejs: menu główne (sześć wież), panele i pasek stanu", "h1"),
          P("Menu główne to miasto z sześcioma wieżami. Najechanie na wieżę pokazuje jej opis i bieżącą wartość z bota, kliknięcie "
            "(albo Enter) przybliża kamerę i otwiera panel. Pasek na dole: wynik, win rate, aktywne sygnały i equity rachunku – każda "
            "wartość ma znacznik źródła (<b>DEMO · symulator</b>, <b>DEMO</b>, <b>REAL</b>, <b>brak danych</b>, <b>nieaktualne</b>, "
            "<b>błąd synchronizacji</b>)."),
          table([["Wieża", "Panel"],
                 ["Lightning Tower", "Live Signals Center: sygnały bota, plan wejścia, cykl życia sygnału, alerty rynku"],
                 ["Ice Tower", "widok Precision (wykresy, reżim, strefy)"],
                 ["Wind Portal", "AI Engine Core: modele, macierz konsensusu, ślad decyzji, Monte Carlo, mapy przepływu modułów"],
                 ["Control Tower", "Bot Management Center: wyniki, sterowanie strategią, limity ryzyka, STOP, Telegram, jakość danych, "
                  "autopilot (tryby), infrastruktura (CPU/RAM), dziennik"],
                 ["Strategy Lab", "silnik strategii, ustawienia, podgląd potoku decyzji, TEST STRATEGY / DEPLOY TO BOT, biblioteka, porównanie"],
                 ["Fire Tower", "Trading Intelligence (terminal)"]], [40, 130]),
          *shot(shots, "ui_cult/03_menu_1920.png", "Menu główne – sześć wież.", width_mm=160),
          P("Menu boczne obszarów (bez zmian) – kliknięcie obszaru otwiera jego pierwszą zakładkę; pozostałe są na pasku zakładek."),
          table([["Obszar", "Zawartość"],
                 ["Menu główne", "miasto sześciu wież (logo w lewym górnym rogu również tu prowadzi)"],
                 ["Precision", "Pulpit, Wykresy MTF, Strefy rynkowe, Scalping MTF, Kontekst rynku, Indykatory, Analiza sygnału, Neural Cyberpunk"],
                 ["Dyscypline", "Scenariusze, Setup silnika S01–S12, SCALPING / HEDGING, Analiza AI, Formacje, Lightning Tower, Strategy Lab"],
                 ["Profits", "Pozycje i ryzyko, Dziennik i wyniki, widok Profits"],
                 ["Modele i trening", "Modele, Centrum treningu, Neural System, Structure Intelligence, Testy, Badania i walidacja, Wind Portal"],
                 ["Ustawienia i diagnostyka", "Ustawienia (z mapą ekranów), Dane i źródła, Diagnostyka, Control Tower"]], [45, 125]),
          box("Control Tower zapisuje ustawienia w konfiguracji bota (progi, filtry, limity ryzyka, szablon i przełączniki Telegram, "
              "presety strategii) – obowiązują od następnej decyzji. Nieprawidłową wartość bot odrzuca i panel to pokazuje. "
              "STOP nowych wejść oraz TEST / DEPLOY strategii wymagają potwierdzenia; tryb wykonania zmienia się tylko w oknie "
              "trybów z potwierdzeniem rachunku.", "warn"),
          P("Pasek stanu (każdy ekran)", "h2"),
          P("U góry każdego ekranu (zwykłego, wież i terminala): instrument i symbol brokera, MT5, jakość i <b>czas ostatnich danych</b>, "
            "rodzaj danych <b>DEMO / LIVE / SYNTETYCZNE</b>, tryb wykonania i STOP."),
          *shot(shots, "ui_interface_129/01_owner_appshell_1920.png", "Pasek stanu i menu obszarów.", crop=(0, 0, 1, 0.42)),
          P("Gdzie są dawne zakładki? <b>Ustawienia i diagnostyka → Ustawienia → Mapa ekranów</b>. Dotychczasowe linki "
            "(np. #/wykresy, #/ai, #/warunki/…) działają bez zmian; dawny link #/licencje otwiera Ustawienia."),
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
          *shot(shots, "ui_chart_prefs/03_settings_dialog.png", "Okno „Ustawienia wykresu”.", width_mm=120, crop=(0.22, 0.13, 0.78, 0.87)),
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
          P("Kronos AI Forecast (1.31) – przetrenowany model, bez treningu w bocie", "h2"),
          bullets(["Instalacja: Wykresy bota → <b>Kronos AI Forecast</b> → <b>Zainstaluj model Kronos</b> albo <b>33_KRONOS_INSTALUJ.bat</b> "
                   "(osobne .venv_kronos, PyTorch CPU, oficjalne wagi NeoQuasar w przypiętych rewizjach, sumy sprawdzane ze źródłem).",
                   "<b>Sprawdź instalację</b> naprawdę ładuje model i robi prognozę testową. Po instalacji działa bez internetu.",
                   "Domyślnie SHADOW (obserwacja) na M5 i M15 dla XAUUSD i BTC (BTC po potwierdzeniu symbolu). Prognoza nie składa zleceń.",
                   "Warunek w strategiach (REQUIRED) tylko po pozytywnej walidacji walk-forward na danych rzeczywistych – może jedynie wstrzymać setup.",
                   "Szczegóły, statusy i rozwiązywanie problemów: <b>INSTRUKCJA_KRONOS.md</b>."]),
          PageBreak()]
    # 5
    s += [P("5 / Paczki do przekazania", "h1"),
          P("Od 1.30 jest jedna wersja programu – bez licencji, bez podziału na OWNER i CLIENT. Inna osoba dostaje tę samą paczkę co Ty:"),
          table([["Paczka", "Dla kogo"],
                 ["PepeMarketWizard_DESKTOP_" + TAG + ".zip", "aplikacja Windows: EXE + wbudowany Python + program (główna paczka)"],
                 ["PepeMarketWizard_" + TAG + ".zip", "sam folder programu (uruchamianie plikami .bat, własny Python)"]], [70, 100]),
          steps(["Przekaż paczkę razem z plikiem <b>.sha256</b> i <b>Instrukcją użytkownika</b>.",
                 "Paczka nie zawiera Twoich danych, kluczy API, haseł MT5, bazy ani dziennika – każdy użytkownik konfiguruje swój MT5 sam.",
                 "Sprawdzenie paczki: <b>python tools\\verify_release.py &lt;paczka&gt;</b> (ścieżki, sumy, brak plików zabronionych)."]),
          box("Program nie blokuje nikomu dostępu – kto ma paczkę, może jej używać. Jeśli chcesz kiedyś wrócić do licencji, system z "
              "wersji 1.27–1.29 jest zachowany w historii repozytorium (git)."),
          PageBreak()]
    # 6
    s += [P("6 / Aktualizacja z 1.29, kopia i powrót", "h1"),
          P("Aktualizację i powrót sprawdzono na kopiach danych (narzędzie <b>tools/migration_check.py</b>): 1.30 uruchamia się na danych "
            "1.29, zachowuje konfigurację, migracje bazy i strefy. Pliki pozostałe po licencjach (license_owner.json, "
            "license_owner_key.*, token licencji) nie są używane ani usuwane – możesz je skasować z folderu <b>data</b>."),
          P("Aktualizacja", "h2"),
          steps(["Zatrzymaj aplikację (STOP nowych wejść → zamknij). Zapisz kopię folderu danych.",
                 "Rozpakuj 1.30 do nowego folderu i uruchom; aplikacja Windows sama robi kopię danych przed migracją.",
                 "Serwer licencji (jeśli go uruchomiłeś) nie jest już potrzebny – możesz go zatrzymać."]),
          P("Powrót do 1.29", "h2"),
          steps(["Zatrzymaj 1.30. Przywróć folder <b>data</b> z kopii sprzed aktualizacji (backups).",
                 "Uruchom program 1.29 z jego folderu (wraca wtedy też system licencji z 1.29)."]),
          P("7 / Typowe problemy", "h1"),
          table([["Objaw", "Co zrobić"],
                 ["MT5 rozłączony / dane nieaktualne", "uruchom terminal, sprawdź logowanie, symbol, historię i 02_DIAGNOSTYKA.bat"],
                 ["Brak stref", "wybierz zakres, sprawdź stan źródła i czas danych, kliknij Wyznacz strefy, odczytaj błąd"],
                 ["Brak wejść", "sprawdź tryb (SIGNALS nie składa zleceń), STOP, ścieżkę główną, limity ryzyka i jakość danych"],
                 ["Trening pominięty", "sprawdź log zadania, zakres historii, luki, RAM i wymagania modelu"]], [60, 110]),
          box("Nie dołączaj do zgłoszeń haseł, tokenów, kluczy prywatnych ani plików bazy. "
              "Wyniki testów: release/RAPORT_KONCOWY.md (PASS / FAIL / BLOCKED).", "warn")]
    return s


# ---------------------------------------------------------------------------------------------------------------- user
def client(shots: Path | None) -> list:
    s: list = [Spacer(1, 18 * mm), P("Instrukcja<br/>użytkownika", "title"),
               P("Instalacja, połączenie z MT5 i korzystanie z PepeMarketWizard 1.30.", "lead"),
               box("<b>Stan:</b> wersja 1.30 działa <b>bez klucza licencji</b> – nie ma okna aktywacji. Ekrany opisane tutaj sprawdzono "
                   "na symulatorze terminala; jeśli Twoja paczka wygląda inaczej, zapytaj osobę, od której ją dostałeś, o aktualną wersję."),
               P("Co przygotować", "h2"),
               bullets(["Komputer z Windows 10/11 i połączeniem z Internetem (pierwsze uruchomienie pobiera składniki).",
                        "Paczkę <b>PepeMarketWizard_DESKTOP_" + TAG + ".zip</b> i jej plik <b>.sha256</b>.",
                        "Terminal MetaTrader 5 z dostępem do własnego rachunku."]),
               box("Nie wysyłaj nikomu hasła do MT5 ani kodów bezpieczeństwa.", "warn"),
               PageBreak()]
    s += [P("1 / Instalacja", "h1"), P("Pierwsze uruchomienie", "h2"),
          steps(["Rozpakuj całą paczkę do nowego folderu. Nie uruchamiaj programu z wnętrza ZIP-a.",
                 "Uruchom <b>PepeMarketWizardDesktop.exe</b> (tytuł okna: <b>PepeMarketWizard " + VERSION + "</b>). Pierwszy start pobiera "
                 "wymagane składniki – może potrwać kilka minut. Postęp widać w małym oknie <b>JOIN THE CULT</b>.",
                 "Gdy launcher pokaże <b>SYSTEM READY</b>, kliknij <b>JOIN THE CULT</b>. Okno się powiększy i po krótkim intro "
                 "(<b>Pomiń intro</b> / Esc) pokaże menu główne – miasto z sześcioma wieżami. Przy pierwszym starcie kreator prosi o "
                 "limity ryzyka i koszty."]),
          *shot(shots, "ui_cult/01_launcher_1920.png", "Launcher JOIN THE CULT.", width_mm=140),
          *shot(shots, "ui_cult/03_menu_1920.png", "Menu główne – sześć wież.", width_mm=150),
          box("Pliki EXE nie są podpisane cyfrowo – Windows SmartScreen może pokazać ostrzeżenie. Porównaj sumę SHA-256 paczki "
              "z plikiem .sha256."),
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
                 ["Tryb, STOP", "SIGNALS / PAPER / AUTO DEMO / AUTO LIVE; STOP zatrzymuje nowe wejścia"]], [55, 115]),
          PageBreak()]
    s += [P("3 / Korzystanie z panelu", "h1"),
          P("Menu główne to miasto sześciu wież: <b>Lightning</b> (sygnały na żywo), <b>Ice</b> (analiza – widok Precision), "
            "<b>Wind</b> (silnik AI i modele), <b>Control</b> (zarządzanie botem), <b>Strategy Lab</b> (strategie) i <b>Fire</b> "
            "(terminal). Najedź na wieżę – zobaczysz opis, kliknij – otworzysz panel. Menu boczne obszarów: <b>Precision</b>, "
            "<b>Dyscypline</b>, <b>Profits</b>, <b>Modele i trening</b>, <b>Ustawienia i diagnostyka</b>. Logo prowadzi do menu głównego."),
          box("Znaczniki przy wartościach mówią, skąd pochodzą: <b>DEMO · symulator</b> (dane syntetyczne), <b>DEMO</b> (rachunek "
              "demonstracyjny), <b>REAL</b>, <b>brak danych</b>, <b>nieaktualne</b>, <b>błąd synchronizacji</b>. Wynik, win rate czy "
              "ROI z symulatora nie są wynikami Twojego rachunku."),
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
    s += [P("4 / Tryby i pomoc", "h1"), P("Tryb pracy", "h2"),
          P("<b>SIGNALS</b> – analiza bez nowych zleceń. <b>PAPER</b> – symulacja. <b>AUTO DEMO</b> i <b>AUTO LIVE</b> – zlecenia na "
            "odpowiednim rachunku, z potwierdzeniem. Zacznij od SIGNALS lub PAPER i rachunku DEMO. <b>STOP</b> zatrzymuje nowe wejścia; "
            "otwarte pozycje są dalej prowadzone (SL/TP po stronie brokera)."),
          P("Rozwiązywanie problemów", "h2"),
          table([["Objaw", "Co zrobić"],
                 ["Program się nie uruchamia", "sprawdź Internet przy pierwszym starcie, uruchom 02_DIAGNOSTYKA.bat i zachowaj wynik"],
                 ["Brak wykresu", "uruchom MT5, sprawdź symbol, historię i stan połączenia"],
                 ["Brak stref", "wybierz interwały, sprawdź czas danych i stan źródła, kliknij Wyznacz strefy"],
                 ["Brak wejść", "sprawdź tryb (SIGNALS nie składa zleceń), STOP, limity ryzyka i jakość danych"]], [55, 115]),
          box("Wyniki historyczne i wyniki modeli nie gwarantują przyszłych wyników. Nie przekazuj nikomu haseł ani pełnych danych "
              "dostępowych.", "warn")]
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
    build(out / "Instrukcja_Klient_PepeMarketWizard.pdf", "UŻYTKOWNIK", client(shots), "PepeMarketWizard – instrukcja użytkownika")
    for n in ("Instrukcja_Administrator_PepeMarketWizard.pdf", "Instrukcja_Klient_PepeMarketWizard.pdf"):
        print(f"{n}: {(out / n).stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
