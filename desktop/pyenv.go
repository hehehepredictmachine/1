package main

// Dependencies of the engine, installed by the app itself on the first start (the user never installs Python or Node.js):
// the bundled interpreter runs pip with the SAME pinned, hash-checked requirements file the classic installer uses
// (--require-hashes --only-binary=:all:) into <home>\pyenv\cp313-<sha256 of the requirements>\site-packages. A new requirements
// file gets a new folder - the previous one stays for a rollback. With <program>\runtime\wheels\ present no network is used.

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// modules the engine cannot start without (same check as 01_INSTALUJ.bat)
const importCheck = "import fastapi, uvicorn, pydantic, anthropic, numpy, websockets, MetaTrader5; print('IMPORT_OK')"

// optional ML modules: a failure is reported, the engine still starts (models that need them show as unavailable)
const mlImportCheck = "import sklearn, xgboost; print('ML_IMPORT_OK')"

type envMarker struct {
	ReqSHA256   string `json:"requirements_sha256"`
	Python      string `json:"python"`
	InstalledAt string `json:"installed_at"`
	Offline     bool   `json:"offline"`
	MLImport    string `json:"ml_import"` // OK or the error of the optional ML check (XGBoost needs the VC++ OpenMP runtime)
}

func fileSHA256(p string) (string, error) {
	f, err := os.Open(p)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// envDir is the dependency folder for the current requirements file.
func envDir(l Layout) (string, string, error) {
	sum, err := fileSHA256(l.Requirements())
	if err != nil {
		return "", "", fmt.Errorf("brak pliku wymagań %s: %w", l.Requirements(), err)
	}
	return filepath.Join(l.EnvRoot, "cp313-"+sum[:12]), sum, nil
}

func sitePackages(dir string) string { return filepath.Join(dir, "site-packages") }

func envReady(dir, sum string) bool {
	b, err := os.ReadFile(filepath.Join(dir, "ok.json"))
	if err != nil {
		return false
	}
	var m envMarker
	return json.Unmarshal(b, &m) == nil && m.ReqSHA256 == sum && exists(sitePackages(dir))
}

// pipArgs builds the install command line (exported for the unit test - nothing here guesses or upgrades versions).
func pipArgs(l Layout, dir string, offline bool) []string {
	a := []string{"-m", "pip", "install", "--disable-pip-version-check", "--no-input", "--no-warn-script-location",
		"--require-hashes", "--only-binary=:all:", "--no-deps", "--target", sitePackages(dir), "-r", l.Requirements()}
	if offline {
		a = append(a, "--no-index", "--find-links", l.WheelsDir())
	}
	return a
}

// ensureEnv installs the dependencies when needed. progress receives the steps, detail the installer's own output lines
// (both shown on the start screen).
func ensureEnv(ctx context.Context, l Layout, progress, detail func(string)) (string, error) {
	if os.Getenv("PMW_SKIP_PYENV") == "1" { // development: the interpreter already has everything
		return "", nil
	}
	dir, sum, err := envDir(l)
	if err != nil {
		return "", err
	}
	if envReady(dir, sum) {
		return sitePackages(dir), nil
	}
	if !exists(l.Python) {
		return "", fmt.Errorf("brak wbudowanego Pythona: %s (paczka niekompletna – rozpakuj ją ponownie)", l.Python)
	}
	offline := exists(l.WheelsDir())
	tmp := dir + ".installing"
	_ = os.RemoveAll(tmp) // leftovers of an interrupted attempt
	if err := os.MkdirAll(tmp, 0o755); err != nil {
		return "", err
	}
	if offline {
		progress("Instalacja składników z paczki (bez internetu)…")
	} else {
		progress("Pierwsze uruchomienie: pobieranie składników z PyPI (ok. 110 MB, sprawdzane sumami SHA-256)…")
	}
	if err := runLogged(ctx, l.Python, pipArgs(l, tmp, offline), nil, detail); err != nil {
		_ = os.RemoveAll(tmp)
		return "", fmt.Errorf("instalacja składników nie powiodła się: %w", err)
	}
	progress("Sprawdzanie składników…")
	env := append(os.Environ(), "PYTHONPATH="+sitePackages(tmp), "PYTHONNOUSERSITE=1")
	if err := runLogged(ctx, l.Python, []string{"-c", importCheck}, env, detail); err != nil {
		_ = os.RemoveAll(tmp)
		return "", fmt.Errorf("składniki zainstalowane, ale nie ładują się: %w", err)
	}
	m := envMarker{ReqSHA256: sum, Python: l.Python, InstalledAt: nowISO(), Offline: offline, MLImport: "OK"}
	if err := runLogged(ctx, l.Python, []string{"-c", mlImportCheck}, env, detail); err != nil {
		m.MLImport = err.Error()
		progress("Uwaga: moduł XGBoost/scikit-learn nie ładuje się (zwykle brak pakietu Microsoft Visual C++ Redistributable x64). " +
			"Bot działa; modele XGBoost będą niedostępne do czasu instalacji tego pakietu.")
	}
	b, _ := json.MarshalIndent(m, "", "  ")
	if err := os.WriteFile(filepath.Join(tmp, "ok.json"), b, 0o644); err != nil {
		return "", err
	}
	_ = os.RemoveAll(dir)
	if err := os.Rename(tmp, dir); err != nil {
		return "", err
	}
	progress("Składniki gotowe.")
	return sitePackages(dir), nil
}

// runLogged runs a command, passing every output line to progress; the error carries the last lines.
func runLogged(ctx context.Context, exe string, args, env []string, progress func(string)) error {
	cmd := exec.CommandContext(ctx, exe, args...)
	hideWindow(cmd)
	if env != nil {
		cmd.Env = env
	}
	pr, pw := io.Pipe()
	cmd.Stdout, cmd.Stderr = pw, pw
	if err := cmd.Start(); err != nil {
		return err
	}
	var tail []string
	done := make(chan struct{})
	go func() {
		sc := bufio.NewScanner(pr)
		sc.Buffer(make([]byte, 64*1024), 1024*1024)
		for sc.Scan() {
			line := strings.TrimSpace(sc.Text())
			if line == "" {
				continue
			}
			tail = append(tail, line)
			if len(tail) > 8 {
				tail = tail[1:]
			}
			progress(line)
		}
		close(done)
	}()
	err := cmd.Wait()
	pw.Close()
	<-done
	if err != nil {
		return errors.New(err.Error() + ": " + strings.Join(tail, " | "))
	}
	return nil
}
