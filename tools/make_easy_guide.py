"""Instrukcja instalacji Apollo23 (dawniej PepeMarketWizard) KROK PO KROKU – w prostym języku (1.44.0; 1.46: nazwa wyświetlana Apollo23).

  release/Instrukcja_Krok_Po_Kroku_PepeMarketWizard.pdf   (+ kopia w docs/ – trafia do paczek)

Dla osoby, która rzadko instaluje programy: duża czcionka, jeden krok naraz, krótkie zdania, pole „☐ Zrobione” przy każdym kroku,
zrzuty prawdziwych ekranów programu (symulator terminala) i rysunki poglądowe okien Windows. Zrzuty: data/logs/ui_easy/*.png
(tools: Playwright na bocie demo w edycji klienta). Bez zrzutów PDF powstaje sam tekst.

  python tools/make_easy_guide.py [--shots data/logs/ui_easy] [--out release]
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_manuals as M  # noqa: E402  (czcionki DejaVu, wersja)

VERSION = M.VERSION
DISPLAY = M.DISPLAY_NAME      # 1.46: user-visible name (splash "APOLLO23 TEAM", button "Zatrzymaj Apollo23"); exe / folders / data paths unchanged
NAME = "Instrukcja_Krok_Po_Kroku_PepeMarketWizard.pdf"
INK = colors.HexColor("#14161c")
GREY = colors.HexColor("#4a505c")
BLUE = colors.HexColor("#1f5fbf")
GREEN_BG, GREEN_LINE = colors.HexColor("#eaf6ee"), colors.HexColor("#7fbf9a")
WARN_BG, WARN_LINE = colors.HexColor("#fff3df"), colors.HexColor("#e2a64a")
RED_BG, RED_LINE = colors.HexColor("#fdeaea"), colors.HexColor("#d98080")
ST: dict[str, ParagraphStyle] = {}
TMP = Path(tempfile.mkdtemp(prefix="pmw_easy_"))


def styles() -> None:
    ST["cover"] = ParagraphStyle("cover", fontName="DejaVu-Bold", fontSize=30, leading=37, textColor=INK, spaceAfter=10)
    ST["coversub"] = ParagraphStyle("coversub", fontName="DejaVu", fontSize=15, leading=22, textColor=GREY, spaceAfter=14)
    ST["h1"] = ParagraphStyle("h1", fontName="DejaVu-Bold", fontSize=22, leading=28, textColor=INK, spaceBefore=4, spaceAfter=10)
    ST["step"] = ParagraphStyle("step", fontName="DejaVu-Bold", fontSize=18, leading=23, textColor=INK, spaceAfter=6)
    ST["p"] = ParagraphStyle("p", fontName="DejaVu", fontSize=13, leading=19.5, textColor=INK, spaceAfter=7, alignment=TA_LEFT)
    ST["do"] = ParagraphStyle("do", parent=ST["p"], leftIndent=14, firstLineIndent=-14, spaceAfter=8)
    ST["small"] = ParagraphStyle("small", fontName="DejaVu", fontSize=10.5, leading=14.5, textColor=GREY, spaceAfter=4)
    ST["cap"] = ParagraphStyle("cap", fontName="DejaVu", fontSize=10, leading=13, textColor=GREY, alignment=TA_CENTER, spaceAfter=8)
    ST["done"] = ParagraphStyle("done", fontName="DejaVu-Bold", fontSize=14, leading=18, textColor=colors.HexColor("#2f7d4f"), spaceBefore=4)
    ST["cell"] = ParagraphStyle("cell", fontName="DejaVu", fontSize=11.5, leading=16, textColor=INK)
    ST["cellb"] = ParagraphStyle("cellb", parent=ST["cell"], fontName="DejaVu-Bold")


def P(text: str, style: str = "p") -> Paragraph:
    return Paragraph(text, ST[style])


def doit(items: list[str]) -> list:
    """Polecenia: każde w osobnej linii, ze strzałką."""
    return [P("➜&nbsp;&nbsp;" + t, "do") for t in items]


def box(text: str, kind: str = "ok") -> Table:
    bg, line = {"ok": (GREEN_BG, GREEN_LINE), "warn": (WARN_BG, WARN_LINE), "stop": (RED_BG, RED_LINE)}[kind]
    t = Table([[P(text)]], colWidths=[170 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("BOX", (0, 0), (-1, -1), 1.4, line),
                           ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                           ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return t


def badge(n: int) -> Drawing:
    d = Drawing(18 * mm, 18 * mm)
    d.add(Circle(9 * mm, 9 * mm, 8.2 * mm, fillColor=BLUE, strokeColor=None))
    d.add(String(9 * mm, 5.6 * mm, str(n), fontName="DejaVu-Bold", fontSize=22 if n < 10 else 18, fillColor=colors.white, textAnchor="middle"))
    return d


def shot(shots: Path | None, name: str, caption: str, width_mm: float = 160, crop: tuple | None = None) -> list:
    if not shots or not (shots / name).exists():
        return []
    src = shots / name
    from PIL import Image as PI
    im = PI.open(src)
    if crop:
        w, h = im.size
        im = im.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
    out = TMP / (src.stem + ("_c" if crop else "") + ".png")
    im.save(out)
    w, h = im.size
    width = width_mm * mm
    height = width * h / w
    if height > 120 * mm:                                       # wysokie wycinki – nie większe niż pół strony
        height = 120 * mm
        width = height * w / h
    img = Image(str(out), width=width, height=height)
    t = Table([[img]], colWidths=[width + 2])
    t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#9aa3b2")), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [Spacer(1, 4), t, P(caption, "cap")]


def step(n: int, title: str, body: list, *, done: bool = True) -> list:
    head = Table([[badge(n), P(title, "step")]], colWidths=[22 * mm, 148 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    tail = [P("☐&nbsp;&nbsp;Zrobione", "done")] if done else []
    return [KeepTogether([head, Spacer(1, 4), *body, *tail]), Spacer(1, 10)]


# ---------------------------------------------------------------------------------------------------------------- rysunki poglądowe
def zip_menu_drawing() -> Drawing:
    """Uproszczony rysunek: prawy przycisk myszy na pliku ZIP -> „Wyodrębnij wszystkie…”."""
    d = Drawing(160 * mm, 52 * mm)
    d.add(Rect(2 * mm, 26 * mm, 52 * mm, 20 * mm, fillColor=colors.HexColor("#f3f5f9"), strokeColor=colors.HexColor("#8a93a3")))
    d.add(Rect(6 * mm, 31 * mm, 10 * mm, 11 * mm, fillColor=colors.HexColor("#f6d36b"), strokeColor=colors.HexColor("#a07f1c")))
    d.add(String(9 * mm, 35 * mm, "ZIP", fontName="DejaVu-Bold", fontSize=7, fillColor=INK))
    d.add(String(19 * mm, 37 * mm, "Apollo23_", fontName="DejaVu", fontSize=8, fillColor=INK))           # 1.46: package file name
    d.add(String(19 * mm, 33 * mm, "DESKTOP_KLIENT…zip", fontName="DejaVu", fontSize=8, fillColor=INK))
    menu = [("Otwórz", False), ("Wyodrębnij wszystkie…", True), ("Udostępnij", False), ("Kopiuj", False), ("Właściwości", False)]
    x0, y0 = 70 * mm, 50 * mm
    d.add(Rect(x0, y0 - len(menu) * 8.4 * mm - 2, 70 * mm, len(menu) * 8.4 * mm + 2, fillColor=colors.white, strokeColor=colors.HexColor("#8a93a3")))
    for i, (t, hi) in enumerate(menu):
        y = y0 - (i + 1) * 8.4 * mm
        if hi:
            d.add(Rect(x0 + 1, y + 1, 70 * mm - 2, 8.4 * mm - 2, fillColor=colors.HexColor("#d7e6ff"), strokeColor=BLUE, strokeWidth=1.6))
        d.add(String(x0 + 5 * mm, y + 2.8 * mm, t, fontName="DejaVu-Bold" if hi else "DejaVu", fontSize=11, fillColor=INK))
    d.add(Line(54 * mm, 36 * mm, 70 * mm, 36 * mm, strokeColor=BLUE, strokeWidth=1.5))
    d.add(String(56 * mm, 38 * mm, "prawy", fontName="DejaVu", fontSize=7.5, fillColor=BLUE))
    d.add(String(56 * mm, 31.5 * mm, "przycisk", fontName="DejaVu", fontSize=7.5, fillColor=BLUE))
    return d


def smartscreen_drawing() -> Drawing:
    """Uproszczony rysunek niebieskiego okna „System Windows ochronił ten komputer”."""
    d = Drawing(160 * mm, 66 * mm)
    d.add(Rect(0, 0, 150 * mm, 64 * mm, fillColor=colors.HexColor("#1a6ec2"), strokeColor=None))
    d.add(String(8 * mm, 53 * mm, "System Windows ochronił ten komputer", fontName="DejaVu-Bold", fontSize=14, fillColor=colors.white))
    d.add(String(8 * mm, 45 * mm, "Usługa Microsoft Defender SmartScreen uniemożliwiła uruchomienie", fontName="DejaVu", fontSize=8.5,
                 fillColor=colors.white))
    d.add(String(8 * mm, 40 * mm, "nierozpoznanej aplikacji…", fontName="DejaVu", fontSize=8.5, fillColor=colors.white))
    d.add(Rect(7 * mm, 29.5 * mm, 37 * mm, 7 * mm, fillColor=None, strokeColor=colors.HexColor("#ffd54a"), strokeWidth=2))
    d.add(String(8.5 * mm, 31.5 * mm, "Więcej informacji", fontName="DejaVu-Bold", fontSize=10, fillColor=colors.white))
    d.add(String(48 * mm, 31.5 * mm, "← 1. kliknij ten napis", fontName="DejaVu-Bold", fontSize=10, fillColor=colors.HexColor("#ffd54a")))
    d.add(Rect(78 * mm, 6 * mm, 30 * mm, 9 * mm, fillColor=colors.HexColor("#e9eef5"), strokeColor=colors.HexColor("#ffd54a"), strokeWidth=2.4))
    d.add(String(93 * mm, 9 * mm, "Uruchom mimo to", fontName="DejaVu-Bold", fontSize=9, fillColor=INK, textAnchor="middle"))
    d.add(Rect(112 * mm, 6 * mm, 30 * mm, 9 * mm, fillColor=colors.HexColor("#e9eef5"), strokeColor=None))
    d.add(String(127 * mm, 9 * mm, "Nie uruchamiaj", fontName="DejaVu", fontSize=9, fillColor=INK, textAnchor="middle"))
    d.add(String(8 * mm, 9 * mm, "2. potem kliknij przycisk →", fontName="DejaVu-Bold", fontSize=10, fillColor=colors.HexColor("#ffd54a")))
    return d


def drawing_block(d: Drawing, caption: str) -> list:
    return [Spacer(1, 4), d, P(caption + " <i>(rysunek poglądowy – u Ciebie okno może wyglądać trochę inaczej)</i>", "cap")]


def table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[P(c, "cellb" if i == 0 else "cell") for c in r] for i, r in enumerate(rows)]
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf5")), ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#a9b2c2")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                           ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return t


# ---------------------------------------------------------------------------------------------------------------- treść
def story(sh: Path | None) -> list:
    pkg = f"Apollo23_DESKTOP_KLIENT_{VERSION.replace('.', '_')}.zip"          # 1.46: package file name (tools/build_desktop.py)
    s: list = [Spacer(1, 22 * mm), P(DISPLAY, "cover"), P("Instalacja krok po kroku", "cover"),
               P("Instrukcja w prostym języku. Rób <b>jeden krok naraz</b>. Gdy skończysz krok, zaznacz <b>☐ Zrobione</b> "
                 "i przejdź do następnego. Nie spiesz się – nic się nie stanie, jeśli zrobisz przerwę.", "coversub"),
               box(f"<b>Wersja programu:</b> {VERSION}<br/><b>Ile to trwa:</b> około 20–40 minut (najdłużej trwa pierwsze uruchomienie).<br/>"
                   "<b>Kto pomoże:</b> osoba, od której masz program (dalej: <b>wydawca</b>)."),
               Spacer(1, 10), P("Zanim zaczniesz – przygotuj", "h1"),
               table([["", "Co", "Dlaczego"],
                      ["☐", "Komputer z <b>Windows 10 albo Windows 11</b>", "Program działa tylko na Windows."],
                      ["☐", "<b>Internet</b>", "Pierwsze uruchomienie pobiera składniki programu (ok. 110 MB)."],
                      ["☐", "Około <b>2 GB</b> wolnego miejsca na dysku", "Na program i jego składniki."],
                      ["☐", "Program <b>MetaTrader 5</b> (MT5) od Twojego brokera i dane do logowania", "Bot pracuje na Twoim koncie w MT5."],
                      ["☐", f"Plik programu od wydawcy: <b>{pkg}</b>", "To jest cały program w jednym pliku."],
                      ["☐", "Kontakt do wydawcy (e-mail, komunikator)", "Wyślesz mu kod komputera i dostaniesz klucz licencyjny."]],
                     [10, 82, 78]),
               PageBreak()]

    s += [P("Bardzo ważne – przeczytaj", "h1"),
          box("<b>To program, który może sam kupować i sprzedawać na Twoim koncie w MT5.</b><br/>Na koncie <b>REAL</b> chodzi o "
              "<b>prawdziwe pieniądze</b>. Możesz stracić pieniądze.", "stop"), Spacer(1, 8),
          *doit(["Bot <b>nie złoży żadnego zlecenia</b>, dopóki sam nie wpiszesz <b>limitów ryzyka</b> (krok 13) i nie wybierzesz "
                 "<b>ścieżki głównej</b> (krok 14). Do tego czasu tylko pokazuje wykresy i sygnały.",
                 "Po każdym uruchomieniu program sam włącza tryb <b>AUTO LIVE</b> (handel na koncie REAL). Jeśli chcesz tylko ćwiczyć – "
                 "w kroku 14 wybierz <b>PAPER</b> (symulacja) i rób to <b>po każdym uruchomieniu</b>.",
                 "Najpierw spróbuj na koncie <b>DEMO</b> (wirtualne pieniądze) – załóż je u swojego brokera.",
                 "Czerwony przycisk <b>STOP</b> (prawy dolny róg) zatrzymuje nowe zlecenia – patrz strona „Jak zatrzymać bota”.",
                 "<b>Nigdy</b> nie wysyłaj nikomu hasła do MT5 ani do konta bankowego. Wydawca potrzebuje tylko <b>kodu komputera (HWID)</b>."]),
          PageBreak(), P("Słowniczek – trudne słowa", "h1"),
          table([["Słowo", "Co to znaczy"],
                 ["Kliknij", "Naciśnij <b>raz lewy</b> przycisk myszy."],
                 ["Kliknij dwa razy", "Naciśnij <b>szybko dwa razy lewy</b> przycisk myszy."],
                 ["Prawy przycisk", "Naciśnij <b>prawy</b> przycisk myszy – otworzy się małe menu."],
                 ["Plik ZIP", "„Paczka”, w której jest wiele plików. Trzeba ją <b>rozpakować</b>."],
                 ["Folder", "Miejsce na dysku z plikami (żółta ikonka teczki)."],
                 ["MT5", "MetaTrader 5 – program brokera do handlu. Bot z nim współpracuje."],
                 ["HWID", "Kod Twojego komputera, np. <b>A1B2C-D3E4F-G5H6J-K7M8N</b>. Wydawca potrzebuje go do klucza."],
                 ["Klucz licencyjny", "Długi tekst zaczynający się od <b>PMW1-</b>. Dostajesz go od wydawcy. Odblokowuje program."]],
                [42, 128]),
          PageBreak()]

    s += [P("Instalacja", "h1")]
    s += step(1, "Sprawdź swój komputer", [*doit(["Kliknij <b>Start</b> (logo Windows w lewym dolnym rogu) → <b>Ustawienia</b> → <b>System</b> → "
                                                  "<b>Informacje</b>. Na dole sprawdź, czy jest napisane <b>Windows 10</b> albo <b>Windows 11</b>.",
                                                  "Sprawdź, czy działa internet (np. otwórz dowolną stronę w przeglądarce)."])])
    s += step(2, "Zainstaluj i zaloguj MetaTrader 5", [*doit(["Zainstaluj <b>MetaTrader 5</b> ze strony swojego brokera (jeśli go jeszcze nie masz).",
                                                               "Otwórz MT5 i zaloguj się na swoje konto. W oknie logowania zaznacz <b>„Zapisz hasło”</b>.",
                                                               "Na początek najlepiej użyj konta <b>DEMO</b>.",
                                                               "<b>Zostaw MT5 włączony.</b> Bot łączy się z tym otwartym programem."]),
                                                       box("Gdy bot ma składać zlecenia (nie tylko symulację), w MT5 na górnym pasku przycisk "
                                                           "<b>Algo Trading</b> musi być włączony (zielony).", "warn")])
    s += step(3, "Zapisz plik programu", [*doit([f"Zapisz plik <b>{pkg}</b> od wydawcy na komputerze – najprościej w folderze <b>Pobrane</b>.",
                                                 "Nie zmieniaj nazwy pliku."])])
    s += step(4, "Rozpakuj plik ZIP", [*doit(["Otwórz folder <b>Pobrane</b>.",
                                               "Kliknij <b>prawym przyciskiem</b> na plik <b>" + pkg + "</b>.",
                                               "Kliknij <b>„Wyodrębnij wszystkie…”</b>.",
                                               "W polu z adresem folderu wpisz: <b>C:\\PepeMarketWizard</b> i kliknij <b>Wyodrębnij</b>.",
                                               "Poczekaj, aż pliki się skopiują. Otworzy się nowy folder."]),
                                        *drawing_block(zip_menu_drawing(), "Prawy przycisk na pliku ZIP → „Wyodrębnij wszystkie…”."),
                                        box("Nie uruchamiaj programu „ze środka” ZIP-a bez rozpakowania – wtedy nie zadziała.", "warn")])
    s += step(5, "Uruchom program", [*doit(["Otwórz folder <b>C:\\PepeMarketWizard</b> (a w nim <b>PepeMarketWizard_Desktop</b>, jeśli jest).",
                                             "Kliknij <b>dwa razy</b> plik <b>PepeMarketWizardDesktop.exe</b>.",
                                             "Wskazówka: kliknij ten plik <b>prawym przyciskiem</b> → <b>Wyślij do</b> → <b>Pulpit (utwórz skrót)</b>. "
                                             "Następnym razem uruchomisz program z Pulpitu."])])
    s += step(6, "Jeśli pojawi się niebieskie okno Windows", [*doit(["Windows czasem ostrzega przed nowymi programami. To normalne.",
                                                                       "Kliknij napis <b>„Więcej informacji”</b>.",
                                                                       "Kliknij przycisk <b>„Uruchom mimo to”</b>."]),
                                                               *drawing_block(smartscreen_drawing(), "Okno „System Windows ochronił ten komputer”."),
                                                               P("Jeśli tego okna nie ma – po prostu przejdź dalej.", "small")])
    s += step(7, "Poczekaj – pierwsze uruchomienie", [*doit([f"Pojawi się czarne okno z napisem <b>{DISPLAY.upper()} TEAM</b>.",
                                                              "Za pierwszym razem program pobiera swoje składniki. To trwa <b>kilka minut</b>. "
                                                              "Na dole widać, co się dzieje.",
                                                              "<b>Nie zamykaj okna.</b> Nie wyłączaj internetu."]),
                                                      *shot(sh, "01_splash_progress.png", "Pierwsze uruchomienie: pobieranie składników (na dole napis, co program robi).",
                                                            150)])
    s += step(8, "Kliknij WEJDŹ", [*doit(["Gdy na dole pojawi się <b>SYSTEM READY</b>, przycisk <b>WEJDŹ →</b> staje się jasny.",
                                           "Kliknij <b>WEJDŹ →</b>."]),
                                    *shot(sh, "02_splash_ready.png", "SYSTEM READY – kliknij WEJDŹ.", 150, crop=(0.2, 0.62, 0.8, 1.0))])
    s += step(9, "Wyślij wydawcy kod komputera (HWID)", [*doit(["Zobaczysz ekran <b>AKTYWACJA LICENCJI</b>.",
                                                                 "Przy napisie <b>TWÓJ HWID</b> kliknij <b>KOPIUJ</b>.",
                                                                 "Otwórz e-mail albo komunikator. Wklej kod (klawisze <b>Ctrl + V</b>) i wyślij go wydawcy.",
                                                                 "Poczekaj, aż wydawca odeśle Ci <b>klucz licencyjny</b>. Program możesz w tym czasie zostawić "
                                                                 "otwarty albo zamknąć."]),
                                                         *shot(sh, "03_license_empty.png", "Ekran aktywacji: Twój HWID i przycisk KOPIUJ.", 120,
                                                               crop=(0.27, 0.12, 0.73, 0.9))])
    s += step(10, "Wklej klucz i kliknij AKTYWUJ", [*doit(["Skopiuj klucz od wydawcy – <b>cały</b>, od <b>PMW1-</b> do samego końca "
                                                            "(zaznacz go myszką i naciśnij <b>Ctrl + C</b>).",
                                                            "W programie kliknij <b>WKLEJ</b> (albo kliknij w pole i naciśnij <b>Ctrl + V</b>).",
                                                            "Kliknij <b>AKTYWUJ</b>.",
                                                            "Gdy zobaczysz zielony napis <b>„Licencja aktywna”</b> – gotowe. Program sam przejdzie dalej."]),
                                                    *shot(sh, "04_license_ok.png", "Licencja aktywna.", 120, crop=(0.27, 0.12, 0.73, 0.9)),
                                                    P("Czerwony napis? Zobacz rozdział „Co zrobić, gdy…”.", "small")])
    s += step(11, "Intro i menu", [*doit(["Pojawi się krótki film (15 sekund, z dźwiękiem). Możesz go pominąć: <b>kliknij</b> w film albo naciśnij <b>Spację</b> lub <b>Esc</b>. "
                                          "Głośnik w prawym dolnym rogu wycisza dźwięk.",
                                          ("Potem zobaczysz menu z trzema planetami: <b>FOREX</b>, <b>CRYPTO</b> (w przygotowaniu) i "
                                           "<b>TraderLifeGame</b> (gra edukacyjna). Główna jest <b>FOREX</b>.")]),
                                   *shot(sh, "05_menu.png", "Menu główne.", 150)])
    s += step(12, "Sprawdź połączenie z MT5", [*doit(["Za pierwszym razem program sam otworzy <b>Ustawienia</b>. Jeśli nie – kliknij ikonkę "
                                                       "<b>☼</b> w prawym dolnym rogu (po najechaniu myszką pokaże się napis „Ustawienia”).",
                                                       "W zakładce <b>MT5</b> sprawdź napis <b>Terminal: CONNECTED</b> i numer Twojego konta.",
                                                       "Jeśli widzisz <b>„Symbol nie znaleziony”</b> – przepisz nazwę złota z listy, którą pokazuje "
                                                       "program (np. <b>XAUUSD</b> albo <b>GOLD</b>), do pola <b>„Dokładny symbol brokera”</b>."]),
                                               *shot(sh, "06_settings_mt5.png", "Ustawienia → MT5: „Terminal: CONNECTED” i numer konta.", 110,
                                                     crop=(0.66, 0.0, 1.0, 0.62))])
    s += step(13, "Limity ryzyka (tylko gdy bot ma handlować)", [*doit(["W Ustawieniach kliknij zakładkę <b>RYZYKO</b>.",
                                                                         "Wpisz wartości, które <b>uzgodniłeś z wydawcą albo opiekunem</b> "
                                                                         "(np. ile procent konta wolno ryzykować w jednej transakcji).",
                                                                         "Kliknij <b>Zapisz</b> (na dole okna).",
                                                                         "<b>Nie wiesz, co wpisać? Nie wpisuj nic.</b> Bez limitów bot nie składa zleceń – "
                                                                         "tylko pokazuje sygnały. To bezpieczne."]),
                                                                 *shot(sh, "07_settings_risk.png", "Ustawienia → Ryzyko.", 100, crop=(0.66, 0.0, 1.0, 0.86))])
    s += step(14, "Wybierz tryb pracy", [*doit(["Kliknij zakładkę <b>TRYB PRACY</b> (na górze panelu).",
                                                "W części <b>3. Wykonanie</b> wybierz:",
                                                "&nbsp;&nbsp;• <b>PAPER</b> – symulacja, <b>bez prawdziwych pieniędzy</b> (dobre na początek),",
                                                "&nbsp;&nbsp;• <b>AUTO DEMO</b> – zlecenia na koncie DEMO,",
                                                "&nbsp;&nbsp;• <b>AUTO LIVE</b> – zlecenia na koncie REAL, <b>prawdziwe pieniądze</b>.",
                                                "Kliknij <b>ZASTOSUJ TRYB WYKONANIA</b>. Przy AUTO DEMO / AUTO LIVE program poprosi o wpisanie numeru konta "
                                                "– przepisz dokładnie to, co pokazuje.",
                                                "W części <b>4. Ścieżka główna</b> wybierz zestaw strategii, który poleci wydawca (bez wyboru bot nie "
                                                "otwiera nowych pozycji)."]),
                                         *shot(sh, "08_mode.png", "Tryb pracy: PAPER (symulacja) albo AUTO LIVE (prawdziwe pieniądze).", 95,
                                               crop=(0.66, 0.41, 1.0, 0.79)),
                                         box("Pamiętaj: po każdym uruchomieniu program wraca do <b>AUTO LIVE</b>. Jeśli chcesz zostać przy "
                                             "symulacji – wybierz PAPER ponownie po każdym uruchomieniu.", "warn")])
    s += step(15, "Wejdź do FOREX i sprawdź, czy wszystko działa", [*doit(["Zamknij panel krzyżykiem <b>✕</b> (prawy górny róg panelu).",
                                                                            "Kliknij planetę <b>FOREX</b>.",
                                                                            "U góry po prawej powinien być napis <b>MT5 POŁĄCZONY</b>."]),
                                                                    *shot(sh, "12_forex_top.png", "Górny pasek ekranu FOREX: MT5 POŁĄCZONY.", 120),
                                                                    box("<b>Gratulacje! Program jest zainstalowany.</b>")], done=True)
    s.append(PageBreak())

    s += [P("Jak zatrzymać bota (STOP)", "h1"),
          *doit(["Kliknij czerwony przycisk <b>STOP</b> w prawym dolnym rogu ekranu.",
                 "<b>1. STOP nowych wejść</b> – bot nie otwiera nowych pozycji. Otwarte pozycje zostają.",
                 "<b>2. Zamknij pozycje bota</b> – wpisz słowo <b>ZAMKNIJ</b> i kliknij <b>Zamknij pozycje</b>. Zamyka pozycje otwarte przez bota.",
                 f"<b>3. Zatrzymaj {DISPLAY}</b> – wyłącza program. Pozycje w MT5 zostają (chroni je Stop Loss u brokera)."]),
          *shot(sh, "13_bottom_icons.png", "Prawy dolny róg: ikonki panelu i czerwony przycisk STOP.", 100),
          *shot(sh, "09_stop.png", "Okno STOP.", 100, crop=(0.66, 0.15, 1.0, 0.66)),
          PageBreak()]

    s += [P("Codzienne uruchamianie", "h1"),
          table([["", "Co zrobić"],
                 ["1", "Włącz <b>MetaTrader 5</b> i sprawdź, czy jesteś zalogowany."],
                 ["2", f"Uruchom <b>{DISPLAY}</b> (skrót na Pulpicie albo PepeMarketWizardDesktop.exe)."],
                 ["3", "Kliknij <b>WEJDŹ →</b> (gdy jest SYSTEM READY). Klucza nie trzeba wpisywać ponownie."],
                 ["4", "Sprawdź <b>TRYB PRACY</b> (PAPER = symulacja, AUTO LIVE = prawdziwe pieniądze)."],
                 ["5", f"Na koniec: STOP → <b>Zatrzymaj {DISPLAY}</b> albo zamknij okno."]],
                [12, 158]),
          PageBreak(),
          KeepTogether([P("Licencja", "h1"),
                        *doit(["Stan licencji: ikonka <b>☼</b> → zakładka <b>LICENCJA</b>. Widać tam, do kiedy jest ważna i ile dni zostało.",
                               "<b>3 dni przed końcem</b> na ekranie pojawi się żółte ostrzeżenie. Poproś wtedy wydawcę o nowy klucz.",
                               "Nowy klucz wklej przyciskiem <b>ZMIEŃ KLUCZ</b> (w zakładce LICENCJA)."]),
                        *shot(sh, "10_license.png", "Zakładka LICENCJA: stan, data końca, HWID i ZMIEŃ KLUCZ.", 160, crop=(0.32, 0.0, 1.0, 0.64))]),
          PageBreak()]

    s += [P("Co zrobić, gdy…", "h1"),
          table([["Co widzisz", "Co zrobić"],
                 ["Niebieskie okno „System Windows ochronił ten komputer”", "Kliknij „Więcej informacji” → „Uruchom mimo to” (krok 6)."],
                 ["Pierwsze uruchomienie stoi bardzo długo albo jest błąd pobierania",
                  "Sprawdź internet. Kliknij <b>Spróbuj ponownie</b>. Jeśli to nie pomaga – uruchom komputer ponownie i spróbuj jeszcze raz."],
                 ["Program pyta, gdzie są dane (<b>Skopiuj dane i uruchom</b> / <b>Zacznij od zera</b>)",
                  "Masz starszą wersję programu. Kliknij <b>Skopiuj dane i uruchom</b>."],
                 ["„Nieprawidłowy klucz licencyjny – zły format” albo „podpis się nie zgadza”",
                  "Klucz jest niepełny. Skopiuj <b>cały</b> klucz jeszcze raz – od PMW1- do samego końca."],
                 ["„Klucz jest przypisany do innego komputera”", "Wyślij wydawcy HWID <b>tego</b> komputera (krok 9) i poproś o nowy klucz."],
                 ["„Licencja wygasła …”", "Poproś wydawcę o nowy klucz i wklej go (krok 10)."],
                 ["„Wykryto cofnięcie zegara systemowego” albo „Błąd zegara systemowego”",
                  "Ustaw poprawną datę i godzinę: <b>Start → Ustawienia → Czas i język → Data i godzina → Ustaw czas automatycznie: Włączone</b>. "
                  "Uruchom program ponownie."],
                 ["W Ustawieniach nie ma „Terminal: CONNECTED”",
                  "Włącz MT5 i zaloguj się. W Ustawieniach → MT5 kliknij <b>Połącz ponownie</b>."],
                 ["„Symbol nie znaleziony”", "Przepisz nazwę złota z listy pokazanej przez program do pola „Dokładny symbol brokera” i kliknij Zapisz."],
                 ["Bot nie składa zleceń", "To normalne bez limitów ryzyka (krok 13) i ścieżki głównej (krok 14). W MT5 włącz przycisk <b>Algo Trading</b>."],
                 ["Okno programu zniknęło", "Uruchom PepeMarketWizardDesktop.exe jeszcze raz. Ikonka programu może też być przy zegarze (prawy dolny róg ekranu)."]],
                [64, 106]),
          Spacer(1, 10), P("Potrzebujesz pomocy?", "h1"),
          *doit(["Zrób zdjęcie ekranu: naciśnij razem klawisze <b>Windows + Shift + S</b> i zaznacz myszką fragment ekranu.",
                 "Wklej obrazek (<b>Ctrl + V</b>) do wiadomości do wydawcy i napisz, w którym kroku jesteś.",
                 "Nigdy nie wysyłaj hasła do MT5."]),
          PageBreak()]

    s += [P("Nowa wersja programu", "h1"),
          *doit([f"Wydawca przyśle nowy plik ZIP. Najpierw zamknij program (STOP → <b>Zatrzymaj {DISPLAY}</b>).",
                 "Rozpakuj nowy plik do <b>nowego</b> folderu, np. <b>C:\\PepeMarketWizard_nowa</b> (jak w kroku 4).",
                 "Uruchom <b>PepeMarketWizardDesktop.exe</b> z nowego folderu. Ustawienia, historia i licencja zostają – są zapisane "
                 "w Twoim folderze użytkownika, nie w folderze programu.",
                 "Gdy nowa wersja działa, stary folder możesz usunąć."]),
          Spacer(1, 6),
          box("Gdzie program trzyma dane: <b>C:\\Users\\(Twoja nazwa)\\AppData\\Local\\PepeMarketWizard</b>. "
              "Licencja: <b>C:\\Users\\(Twoja nazwa)\\AppData\\Roaming\\PepeMarketWizard\\license.dat</b>. Nie usuwaj tych folderów."),
          Spacer(1, 12),
          P(f"{DISPLAY} {VERSION} · zrzuty ekranu z symulatora (dane testowe) – na Twoim komputerze liczby będą inne.", "small")]
    return s


def deco(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("DejaVu", 9)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, A4[1] - 12 * mm, f"{DISPLAY} – instalacja krok po kroku")
    canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Strona {doc.page}")
    canvas.restoreState()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "data" / "logs" / "ui_easy"))
    ap.add_argument("--out", default=str(ROOT / "release"))
    a = ap.parse_args()
    M.fonts()
    styles()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sh = Path(a.shots) if Path(a.shots).is_dir() else None
    path = out / NAME
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=16 * mm,
                            title=f"{DISPLAY} – instalacja krok po kroku", author=DISPLAY,
                            subject=f"{DISPLAY} {VERSION}", creator="tools/make_easy_guide.py", initialFontName="DejaVu")
    doc.build(story(sh), onFirstPage=deco, onLaterPages=deco)
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{NAME}: {path.stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
