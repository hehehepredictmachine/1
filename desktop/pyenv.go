package main

// Dependencies of the engine, installed by the app itself on the first start (the user never installs Python or Node.js):
// the bundled interpreter runs pip with the SAME pinned, hash-checked requirements file the classic installer uses
// (--require-hashes --only-binary=:all:) into <home>\pyenv\cp313-<sha256 of the requirements>\site-packages. A new requirements
// file gets a new folder - the previous one stays for a rollback. With <program>\runtime\wheels\ present no network is used.

import (
	"bufio"
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
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
		ok, bad := envIntact(sitePackages(dir), l.Requirements())
		if ok {
			return sitePackages(dir), nil
		}
		// 1.40.4: a file of an installed package is gone or truncated (antivirus quarantine, disk cleanup, interrupted copy) - the engine
		// would die with ModuleNotFoundError. The folder is set aside and the components are installed again.
		progress("Składniki bota są uszkodzone (" + bad + ") – ponowna instalacja…")
		if err := discardEnv(dir); err != nil {
			return "", fmt.Errorf("uszkodzonego folderu składników %s nie da się usunąć (%w) – zamknij programy Python i spróbuj ponownie", dir, err)
		}
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
	if err := runLogged(ctx, l.Python, pipArgs(l, tmp, offline), pyChildEnv(), detail); err != nil {
		_ = os.RemoveAll(tmp)
		return "", fmt.Errorf("instalacja składników nie powiodła się: %w", err)
	}
	progress("Sprawdzanie składników…")
	env := pyChildEnv("PYTHONPATH=" + sitePackages(tmp))
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
	if err := renameRetry(tmp, dir); err != nil {
		return "", fmt.Errorf("nie można zapisać folderu składników %s (%w) – zwykle blokuje go program antywirusowy; spróbuj ponownie", dir, err)
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

// foreignPyEnv: variables of the user's machine that must never reach the bundled Python or pip (1.40.3). A PYTHONHOME left by another
// Python breaks the interpreter at start; PIP_REQUIRE_VIRTUALENV / PIP_USER / PIP_TARGET / PIP_NO_INDEX change where pip installs or
// make it refuse. Proxy settings (HTTPS_PROXY), PATH and TEMP stay.
var foreignPyEnv = map[string]bool{"PYTHONPATH": true, "PYTHONHOME": true, "PYTHONSTARTUP": true, "PYTHONUSERBASE": true,
	"PYTHONEXECUTABLE": true, "PYTHONSAFEPATH": true, "PYTHONNOUSERSITE": true, "PYTHONUTF8": true, "PYTHONIOENCODING": true,
	"VIRTUAL_ENV": true, "CONDA_PREFIX": true, "__PYVENV_LAUNCHER__": true, "PIP_TARGET": true, "PIP_PREFIX": true, "PIP_USER": true,
	"PIP_ROOT": true, "PIP_REQUIRE_VIRTUALENV": true, "PIP_NO_INDEX": true, "PIP_FIND_LINKS": true, "PIP_ONLY_BINARY": true,
	"PIP_NO_BINARY": true, "PIP_CONSTRAINT": true, "PIP_REQUIREMENT": true, "PIP_NO_DEPS": true}

// pyChildEnv: the machine's environment without foreignPyEnv, with user site off and UTF-8 I/O, plus extra "K=V" entries.
func pyChildEnv(extra ...string) []string {
	env := []string{}
	for _, kv := range os.Environ() {
		if foreignPyEnv[strings.ToUpper(strings.SplitN(kv, "=", 2)[0])] {
			continue
		}
		env = append(env, kv)
	}
	// pip.ini stays readable (company proxy / mirror), but its require-virtualenv / user switches are overridden here
	env = append(env, "PYTHONNOUSERSITE=1", "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8", "PIP_REQUIRE_VIRTUALENV=0", "PIP_USER=0")
	return append(env, extra...)
}

// renameRetry replaces dst with src; antivirus scanners briefly lock freshly written files on Windows, so it retries for ~10 s.
func renameRetry(src, dst string) error {
	var err error
	for i := 0; i < 20; i++ {
		_ = os.RemoveAll(dst)
		if err = os.Rename(src, dst); err == nil {
			return nil
		}
		time.Sleep(500 * time.Millisecond)
	}
	return err
}

// envIntact: every file pip recorded for the installed packages (<pkg>.dist-info/RECORD: path,hash,size) exists with that size, and
// there is a package for every pin of the requirements file. Byte-cheap (stat only) - runs on every start. Returns what is wrong.
func envIntact(site, requirements string) (bool, string) {
	records, _ := filepath.Glob(filepath.Join(site, "*.dist-info", "RECORD"))
	if pins := countPins(requirements); len(records) < pins {
		return false, fmt.Sprintf("zainstalowanych pakietów %d z %d", len(records), pins)
	}
	for _, rec := range records {
		f, err := os.Open(rec)
		if err != nil {
			return false, filepath.Base(filepath.Dir(rec)) + "/RECORD"
		}
		r := csv.NewReader(f)
		r.FieldsPerRecord, r.LazyQuotes = -1, true
		rows, err := r.ReadAll()
		f.Close()
		if err != nil {
			return false, filepath.Base(filepath.Dir(rec)) + "/RECORD nieczytelny"
		}
		for _, row := range rows {
			if len(row) == 0 {
				continue
			}
			rel := row[0]
			if rel == "" || strings.HasPrefix(rel, "..") || strings.Contains(rel, "__pycache__") || strings.HasSuffix(rel, ".pyc") {
				continue // scripts outside site-packages, bytecode caches (rebuilt by Python)
			}
			st, err := os.Stat(filepath.Join(site, filepath.FromSlash(rel)))
			if err != nil {
				return false, "brak " + rel
			}
			if len(row) >= 3 && row[2] != "" {
				if n, err := strconv.ParseInt(row[2], 10, 64); err == nil && st.Size() != n {
					return false, "uszkodzony " + rel
				}
			}
		}
	}
	return true, ""
}

func countPins(requirements string) int {
	b, err := os.ReadFile(requirements)
	if err != nil {
		return 0
	}
	n := 0
	for _, ln := range strings.Split(string(b), "\n") {
		ln = strings.TrimSpace(ln)
		if ln != "" && !strings.HasPrefix(ln, "#") && !strings.HasPrefix(ln, "--") && strings.Contains(ln, "==") {
			n++
		}
	}
	return n
}

// discardEnv removes a damaged dependency folder; when files are locked it is renamed aside instead (removed on a later start).
func discardEnv(dir string) error {
	if err := os.RemoveAll(dir); err == nil {
		return nil
	}
	_ = os.Remove(filepath.Join(dir, "ok.json")) // never "ready" again, even if the rename below fails too
	aside := fmt.Sprintf("%s.broken-%d", dir, time.Now().Unix())
	if err := os.Rename(dir, aside); err != nil {
		if exists(filepath.Join(dir, "ok.json")) {
			return err
		}
	}
	return nil
}

// cleanupBrokenEnvs removes folders set aside by discardEnv (best effort, files may still be locked).
func cleanupBrokenEnvs(root string) {
	old, _ := filepath.Glob(filepath.Join(root, "*.broken-*"))
	for _, d := range old {
		_ = os.RemoveAll(d)
	}
}

// importFailure: the engine died because a component could not be imported (damaged / incomplete dependency folder).
func importFailure(err error) bool {
	if err == nil {
		return false
	}
	m := err.Error()
	return strings.Contains(m, "ModuleNotFoundError") || strings.Contains(m, "ImportError") || strings.Contains(m, "DLL load failed")
}

// invalidateEnv marks the current dependency folder as not ready, so ensureEnv installs it again.
func invalidateEnv(l Layout) {
	if dir, _, err := envDir(l); err == nil {
		_ = discardEnv(dir)
	}
}
