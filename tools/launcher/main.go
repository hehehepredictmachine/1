// PepeMarketWizard.exe - launcher of the existing, tested Windows scripts (install, calibration + training, context
// indicator calibration, diagnostics, bot start/stop). It contains no trading logic, never sends orders and never changes
// the Execution Lock: every action runs the corresponding .bat from the program folder in this console window.
//
// Usage: PepeMarketWizard.exe                -> menu
//        PepeMarketWizard.exe trening XAUUSD -> install if needed, then calibration + training (XAUUSD | BTC | OBA)
//        PepeMarketWizard.exe install | kontekst | diagnostyka | start | stop
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

const version = "1.21.0"

var required = []string{
	`tools\check_python.py`, `tools\trening.cmd`, `backend\masterquo\__main__.py`, `backend\mq_instruments.py`,
	`frontend\dist\index.html`, `MANIFEST_SHA256.txt`, `INSTALUJ_TRENING.bat`, `TRENUJ_XAUUSD.bat`,
}

type settings struct {
	RAMBudgetMB int `json:"ram_budget_mb"`
}

func root() string {
	exe, err := os.Executable()
	if err != nil {
		return "."
	}
	if r, err := filepath.EvalSymlinks(exe); err == nil {
		exe = r
	}
	return filepath.Dir(exe)
}

func settingsPath(r string) string { return filepath.Join(r, "data", "launcher.json") }

func loadSettings(r string) settings {
	s := settings{RAMBudgetMB: 8192}
	if b, err := os.ReadFile(settingsPath(r)); err == nil {
		_ = json.Unmarshal(b, &s)
	}
	if s.RAMBudgetMB < 512 {
		s.RAMBudgetMB = 8192
	}
	return s
}

func saveSettings(r string, s settings) error {
	_ = os.MkdirAll(filepath.Join(r, "data"), 0o755)
	b, _ := json.MarshalIndent(s, "", "  ")
	return os.WriteFile(settingsPath(r), b, 0o644)
}

func missingFiles(r string) []string {
	var miss []string
	for _, f := range required {
		if _, err := os.Stat(filepath.Join(r, filepath.FromSlash(strings.ReplaceAll(f, `\`, "/")))); err != nil {
			miss = append(miss, f)
		}
	}
	return miss
}

func exists(p string) bool { _, err := os.Stat(p); return err == nil }

func venvReady(r string) bool {
	return exists(filepath.Join(r, ".venv", "Scripts", "python.exe"))
}

// runBat runs one script of the program folder in this console (stdin/stdout shared), with the RAM budget in the environment.
func runBat(r string, s settings, name string, args ...string) int {
	p := filepath.Join(r, name)
	if !exists(p) {
		fmt.Printf("[BLAD] Brak pliku %s w folderze programu.\n", name)
		return 2
	}
	env := append(os.Environ(), "MQ_RAM_BUDGET_MB="+strconv.Itoa(s.RAMBudgetMB))
	fmt.Printf("\n>>> %s %s\n", name, strings.Join(args, " "))
	return runScript(r, p, args, env)
}

func ensureInstalled(r string, s settings) bool {
	if venvReady(r) {
		return true
	}
	fmt.Println("[..] Srodowisko nie jest zainstalowane - uruchamiam instalacje (INSTALUJ_TRENING.bat).")
	runBat(r, s, "INSTALUJ_TRENING.bat")
	if !venvReady(r) {
		fmt.Println("[BLAD] Instalacja nie utworzyla .venv - szczegoly w data\\logs\\instalacja_*.log")
		return false
	}
	return true
}

func training(r string, s settings, inst string) int {
	if !ensureInstalled(r, s) {
		return 2
	}
	bat := map[string]string{"XAUUSD": "TRENUJ_XAUUSD.bat", "BTC": "TRENUJ_BTCUSDT.bat", "OBA": "TRENUJ_OBA.bat"}[strings.ToUpper(inst)]
	if bat == "" {
		fmt.Println("[BLAD] Instrument: XAUUSD, BTC albo OBA")
		return 2
	}
	return runBat(r, s, bat)
}

func action(r string, s *settings, cmd string, rest []string) int {
	switch strings.ToLower(cmd) {
	case "install", "instalacja":
		return runBat(r, *s, "INSTALUJ_TRENING.bat")
	case "trening", "train":
		inst := "XAUUSD"
		if len(rest) > 0 {
			inst = rest[0]
		}
		return training(r, *s, inst)
	case "kontekst", "context":
		if !ensureInstalled(r, *s) {
			return 2
		}
		return runBat(r, *s, "29_CONTEXT_INDICATORS.bat")
	case "menu-treningu":
		if !ensureInstalled(r, *s) {
			return 2
		}
		return runBat(r, *s, "00_TRENING_START.bat")
	case "diagnostyka", "diag":
		return runBat(r, *s, "DIAGNOSTYKA_TRENINGU.bat")
	case "start":
		if !ensureInstalled(r, *s) {
			return 2
		}
		return runBat(r, *s, "03_START_MASTERQUO.bat")
	case "stop":
		return runBat(r, *s, "04_STOP_MASTERQUO.bat")
	}
	fmt.Println("[BLAD] Nieznane polecenie:", cmd)
	return 2
}

func main() {
	initConsole()
	r := root()
	s := loadSettings(r)
	fmt.Printf("PepeMarketWizard %s - launcher (folder: %s)\n", version, r)
	fmt.Println("Trening i kalibracja dzialaja offline/SHADOW: nie wysylaja zlecen i nie zmieniaja Execution Lock.")
	if miss := missingFiles(r); len(miss) > 0 {
		fmt.Println("\n[BLAD] Niekompletny folder programu - brak:", strings.Join(miss, ", "))
		fmt.Println("       Rozpakuj CALY plik ZIP (prawy klik - Wyodrebnij wszystkie) do nowego, pustego folderu")
		fmt.Println("       i uruchom PepeMarketWizard.exe z tego folderu (nie z podgladu ZIP).")
		pause()
		os.Exit(2)
	}
	if len(os.Args) > 1 {
		os.Exit(action(r, &s, os.Args[1], os.Args[2:]))
	}
	in := bufio.NewReader(os.Stdin)
	for {
		state := "NIE zainstalowane (opcja 1)"
		if venvReady(r) {
			state = "zainstalowane"
		}
		fmt.Printf("\n=== PepeMarketWizard %s === srodowisko: %s, budzet RAM treningu: %d MB\n", version, state, s.RAMBudgetMB)
		fmt.Println(" 1. Instalacja / naprawa srodowiska (Python 3.13/3.12 x64, .venv + .venv_candles)")
		fmt.Println(" 2. Kalibracja + trening modeli XAUUSD (eksport z MT5 -> wszystkie zadania -> raport)")
		fmt.Println(" 3. Kalibracja + trening modeli BTC")
		fmt.Println(" 4. Kalibracja + trening XAUUSD i BTC")
		fmt.Println(" 5. Kalibracja wskaznikow kontekstu VAMD / FD / SMC + native MQL5 (menu)")
		fmt.Println(" 6. Menu treningu (wyniki, wznowienie, rollback, test instalacji)")
		fmt.Println(" 7. Diagnostyka treningu (Python, MT5, symbole, RAM)")
		fmt.Println(" 8. Start bota (monitor w przegladarce)")
		fmt.Println(" 9. Stop bota")
		fmt.Println(" R. Zmien budzet RAM treningu")
		fmt.Println(" 0. Wyjscie")
		fmt.Print("Wybor: ")
		line, err := in.ReadString('\n')
		if err != nil {
			return
		}
		switch strings.ToUpper(strings.TrimSpace(line)) {
		case "1":
			action(r, &s, "install", nil)
		case "2":
			action(r, &s, "trening", []string{"XAUUSD"})
		case "3":
			action(r, &s, "trening", []string{"BTC"})
		case "4":
			action(r, &s, "trening", []string{"OBA"})
		case "5":
			action(r, &s, "kontekst", nil)
		case "6":
			action(r, &s, "menu-treningu", nil)
		case "7":
			action(r, &s, "diagnostyka", nil)
		case "8":
			action(r, &s, "start", nil)
		case "9":
			action(r, &s, "stop", nil)
		case "R":
			fmt.Print("Budzet RAM w MB (np. 8192 = 8 GB): ")
			v, _ := in.ReadString('\n')
			if n, err := strconv.Atoi(strings.TrimSpace(v)); err == nil && n >= 512 {
				s.RAMBudgetMB = n
				if err := saveSettings(r, s); err != nil {
					fmt.Println("[BLAD] zapis ustawien:", err)
				} else {
					fmt.Println("[OK] zapisano w data\\launcher.json")
				}
			} else {
				fmt.Println("[BLAD] podaj liczbe >= 512")
			}
		case "0", "Q":
			return
		}
	}
}

func pause() {
	fmt.Print("Nacisnij Enter...")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
}
