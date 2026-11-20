package main

// Supervision of the engine process (python -m masterquo serve). Exactly one engine per data folder: the engine itself holds an
// instance lock, and the shell first asks /api/v1/health - an engine that is already running (e.g. started by
// 03_START_MASTERQUO.bat) is ATTACHED, never duplicated, and left running when the window closes.
//
// Start: hidden process, console output to <data>\logs\engine_console.log, ready when /api/v1/health answers with this app's
// name. Unexpected exit: restart after 2 / 5 / 15 / 30 / 60 s, at most 5 restarts in 10 minutes, then FAILED (shown to the user
// with the log path). Restart requested by the panel: <data>\runtime\restart.request + a normal shutdown -> immediate start.
// Stop: the engine's own shutdown endpoint with its token (data\runtime\shutdown.token), then a forced kill after the timeout.
// On Windows the process belongs to a Job Object that is closed with the shell, so a crashed shell never leaves an orphan engine.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const appName = "PepeMarketWizard"

type EngineState string

const (
	EngineStopped  EngineState = "STOPPED"
	EngineStarting EngineState = "STARTING"
	EngineRunning  EngineState = "RUNNING"
	EngineExternal EngineState = "EXTERNAL" // started outside this app - attached, not owned
	EngineCrashed  EngineState = "CRASHED"  // exited unexpectedly, restart pending
	EngineFailed   EngineState = "FAILED"   // restart limit reached
)

type Engine struct {
	l       Layout
	site    string
	logf    func(string)
	onState func(EngineState, string)

	mu       sync.Mutex
	cmd      *exec.Cmd
	proc     procGuard
	state    EngineState
	detail   string
	stopping bool
	restarts []time.Time
	exited   chan struct{}
	starting *exec.Cmd // the process spawn() is still waiting for: its early exit is reported by spawn, not auto-restarted
	client   *http.Client
	extra    []string // extra engine arguments (tests: --demo = simulator instead of MetaTrader5)
}

func newEngine(l Layout, site string, logf func(string), onState func(EngineState, string)) *Engine {
	return &Engine{l: l, site: site, logf: logf, onState: onState, state: EngineStopped, client: &http.Client{Timeout: 3 * time.Second}}
}

func (e *Engine) set(s EngineState, detail string) {
	e.mu.Lock()
	e.state, e.detail = s, detail
	e.mu.Unlock()
	e.logf(fmt.Sprintf("silnik: %s %s", s, detail))
	if e.onState != nil {
		e.onState(s, detail)
	}
}

func (e *Engine) State() (EngineState, string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.state, e.detail
}

// Port of the engine: data\config.json server.port, else the engine's default.
func (e *Engine) Port() int {
	if isStudio() {
		var st struct {
			Port int `json:"port"`
		}
		if b, err := os.ReadFile(filepath.Join(e.l.StudioDir(), "settings.json")); err == nil && json.Unmarshal(b, &st) == nil && st.Port >= 1024 {
			return st.Port
		}
		return 8780
	}
	var c struct {
		Server struct {
			Port int `json:"port"`
		} `json:"server"`
	}
	if b, err := os.ReadFile(filepath.Join(e.l.DataDir, "config.json")); err == nil && json.Unmarshal(b, &c) == nil && c.Server.Port >= 1024 {
		return c.Server.Port
	}
	return 8765
}

func (e *Engine) URL() string { return fmt.Sprintf("http://127.0.0.1:%d/", e.Port()) }

// healthy = this app answers on the port (another program on the port is not mistaken for the engine).
func (e *Engine) healthy() bool {
	ok, _ := e.health()
	return ok
}

// health: whether this app answers on the port, and the version of the engine that answers ("" when it does not say).
func (e *Engine) health() (bool, string) {
	r, err := e.client.Get(e.URL() + healthPath())
	if err != nil {
		return false, ""
	}
	defer r.Body.Close()
	var h struct {
		OK      bool   `json:"ok"`
		App     string `json:"app"`
		Version string `json:"version"`
	}
	ok := r.StatusCode == 200 && json.NewDecoder(r.Body).Decode(&h) == nil && h.OK && strings.EqualFold(h.App, expectedApp())
	return ok, h.Version
}

// replaceOutdated (1.40.3): an engine of ANOTHER version answers on our port (e.g. the previous version started from a .bat file or
// left running) - attaching to it would show the old program after an update. When it belongs to this data folder (it accepts the
// shutdown token from <data>\runtime\shutdown.token) it is asked to stop and the current version starts. Returns true when the port
// is free again.
func (e *Engine) replaceOutdated(running string) bool {
	tok, err := os.ReadFile(filepath.Join(e.l.RuntimeDir(), "shutdown.token"))
	if err != nil {
		return false
	}
	req, _ := http.NewRequest("POST", e.URL()+"api/v1/admin/shutdown", strings.NewReader("{}"))
	req.Header.Set("x-mq-shutdown", strings.TrimSpace(string(tok)))
	req.Header.Set("Content-Type", "application/json")
	r, err := e.client.Do(req)
	if err != nil {
		return false
	}
	r.Body.Close()
	if r.StatusCode >= 300 {
		return false // not our engine (another data folder) - never stopped
	}
	e.logf("silnik: działała wersja " + running + " – zatrzymano ją, uruchamiam " + version)
	for i := 0; i < 75; i++ { // up to 30 s for its graceful stop (positions stay protected by SL/TP on the broker side)
		time.Sleep(400 * time.Millisecond)
		if ok, _ := e.health(); !ok && !e.portTakenByOther() {
			return true
		}
	}
	return false
}

func healthPath() string {
	if isStudio() {
		return "api/studio/health"
	}
	return "api/v1/health"
}

func expectedApp() string {
	if isStudio() {
		return "PepeTrainingStudio"
	}
	return appName
}

func (e *Engine) portTakenByOther() bool {
	r, err := e.client.Get(e.URL() + healthPath())
	if err != nil {
		return false
	}
	r.Body.Close()
	return !e.healthy()
}

func (e *Engine) env() []string {
	sep := string(os.PathListSeparator)
	pp := filepath.Join(e.l.AppDir, "backend")
	if e.site != "" {
		pp += sep + e.site
	}
	env := []string{}
	for _, kv := range os.Environ() { // never inherit a foreign PYTHONPATH / PYTHONHOME / pip settings (another Python on the machine)
		k := strings.ToUpper(strings.SplitN(kv, "=", 2)[0])
		if foreignPyEnv[k] || k == "MASTERQUO_DATA_DIR" {
			continue
		}
		env = append(env, kv)
	}
	if isStudio() { // own data folder; the bot's data folder only as the read-only candle source / inbox / shared export lock
		return append(env, "PYTHONPATH="+pp, "PYTHONNOUSERSITE=1", "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8",
			"MASTERQUO_DATA_DIR="+e.l.StudioDir(), "MQ_STUDIO_DATA_DIR="+e.l.StudioDir(), "MQ_BOT_DATA_DIR="+e.l.DataDir,
			"PMW_DESKTOP=1", "PMW_DESKTOP_EXE="+e.l.Exe)
	}
	return append(env, "PYTHONPATH="+pp, "PYTHONNOUSERSITE=1", "PYTHONUTF8=1", "PYTHONIOENCODING=utf-8",
		"MASTERQUO_DATA_DIR="+e.l.DataDir, "PMW_DESKTOP=1", "PMW_DESKTOP_EXE="+e.l.Exe)
}

func (e *Engine) args() []string {
	if isStudio() {
		return append([]string{"-m", "masterquo", "studio"}, e.extra...)
	}
	return append([]string{"-m", "masterquo", "serve", "--no-browser"}, e.extra...)
}

func (e *Engine) consoleLog() (*os.File, error) {
	if err := os.MkdirAll(e.l.LogsDir(), 0o755); err != nil {
		return nil, err
	}
	p := filepath.Join(e.l.LogsDir(), "engine_console.log")
	if st, err := os.Stat(p); err == nil && st.Size() > 10<<20 {
		_ = os.Rename(p, p+".1")
	}
	return os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
}

// Start attaches to a running engine or starts one and waits until it answers (first start may migrate the database).
func (e *Engine) Start(ctx context.Context) error {
	if ok, running := e.health(); ok {
		if e.Owned() { // our own process from an earlier attempt finished starting meanwhile
			e.set(EngineRunning, "")
			return nil
		}
		if running != "" && version != "" && running != version && !isStudio() {
			if e.replaceOutdated(running) {
				return e.spawn(ctx)
			}
			e.set(EngineExternal, "działa silnik w wersji "+running+" (ta aplikacja: "+version+") – podłączono; zamknij go, aby używać nowej wersji")
			return nil
		}
		e.set(EngineExternal, "silnik działał już wcześniej – podłączono bez uruchamiania drugiej kopii")
		return nil
	}
	if e.portTakenByOther() {
		err := fmt.Errorf("port %d jest zajęty przez inny program – zmień server.port w %s", e.Port(), filepath.Join(e.l.DataDir, "config.json"))
		e.set(EngineFailed, err.Error())
		return err
	}
	return e.spawn(ctx)
}

func (e *Engine) spawn(ctx context.Context) error {
	e.set(EngineStarting, "uruchamianie silnika…")
	logFile, err := e.consoleLog()
	if err != nil {
		return err
	}
	cmd := exec.Command(e.l.Python, e.args()...)
	cmd.Dir = e.l.AppDir
	cmd.Env = e.env()
	cmd.Stdout, cmd.Stderr = logFile, logFile
	hideWindow(cmd)
	fmt.Fprintf(logFile, "\n===== %s start: %s %s\n", nowISO(), e.l.Python, strings.Join(e.args(), " "))
	var logFrom int64
	if st, err := logFile.Stat(); err == nil {
		logFrom = st.Size()
	}
	if err := cmd.Start(); err != nil {
		logFile.Close()
		e.set(EngineFailed, "nie można uruchomić Pythona: "+err.Error())
		return err
	}
	guard := guardProcess(cmd)
	exited := make(chan struct{})
	e.mu.Lock()
	e.cmd, e.proc, e.stopping, e.exited, e.starting = cmd, guard, false, exited, cmd
	e.mu.Unlock()
	started := func() {
		e.mu.Lock()
		if e.starting == cmd {
			e.starting = nil
		}
		e.mu.Unlock()
	}
	go func() {
		werr := cmd.Wait()
		logFile.Close()
		if guard != nil {
			guard.Close() // closes the Job Object: nothing the engine started outlives it
		}
		close(exited)
		e.afterExit(ctx, cmd, werr)
	}()
	deadline := time.Now().Add(120 * time.Second)
	for time.Now().Before(deadline) {
		select {
		case <-exited:
			return e.earlyExit(ctx, cmd, logFrom)
		case <-ctx.Done():
			started()
			return ctx.Err()
		case <-time.After(400 * time.Millisecond):
		}
		if e.healthy() {
			started()
			e.set(EngineRunning, "")
			return nil
		}
	}
	started()
	return errors.New("silnik nie odpowiedział w ciągu 120 s – szczegóły: " + filepath.Join(e.l.LogsDir(), "engine_console.log"))
}

// earlyExit: the engine ended before it answered. Exit codes of `masterquo serve`: 0 = an instance of the app already answers
// (attach), 3 = port taken by another program, 4 = another engine holds this data folder's lock (it is still starting - wait for
// it), 5 = startup error with traceback. Every other case: the last lines of the console log go straight into the message.
func (e *Engine) earlyExit(ctx context.Context, cmd *exec.Cmd, logFrom int64) error {
	code := -1
	if cmd.ProcessState != nil {
		code = cmd.ProcessState.ExitCode()
	}
	logPath := filepath.Join(e.l.LogsDir(), "engine_console.log")
	e.mu.Lock()
	if e.starting == cmd {
		e.starting = nil
	}
	e.mu.Unlock()
	if code == 0 || code == 4 { // another engine of this folder answers or is about to: attach instead of failing
		for i := 0; i < 150; i++ {
			if e.healthy() {
				e.set(EngineExternal, "silnik działał już wcześniej – podłączono bez uruchamiania drugiej kopii")
				return nil
			}
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(400 * time.Millisecond):
			}
		}
	}
	var msg string
	switch code {
	case 3:
		msg = fmt.Sprintf("port %d jest zajęty przez inny program – zmień server.port w %s", e.Port(), filepath.Join(e.l.DataDir, "config.json"))
	case 4:
		msg = "inna kopia silnika trzyma ten folder danych, ale nie odpowiada (zawieszona po poprzednim uruchomieniu). " +
			"Zamknij procesy python.exe PepeMarketWizard w Menedżerze zadań albo uruchom ponownie komputer i spróbuj jeszcze raz."
	default:
		msg = fmt.Sprintf("silnik zakończył się podczas startu (kod %d)", code)
	}
	if t := logTail(logPath, logFrom, 14); t != "" {
		msg += "\n\nOstatnie linie logu:\n" + t
	}
	msg += "\n\nPełny log: " + logPath
	e.set(EngineFailed, msg)
	return errors.New(msg)
}

// logTail: the last n non-empty lines written to the console log since offset `from` (this start only), at most ~1600 characters.
func logTail(p string, from int64, n int) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	if from > 0 && from <= int64(len(b)) {
		b = b[from:]
	}
	lines := []string{}
	for _, ln := range strings.Split(strings.ReplaceAll(string(b), "\r\n", "\n"), "\n") {
		if strings.TrimSpace(ln) != "" {
			lines = append(lines, strings.TrimRight(ln, " \t"))
		}
	}
	if len(lines) > n {
		lines = lines[len(lines)-n:]
	}
	out := strings.Join(lines, "\n")
	if r := []rune(out); len(r) > 1600 {
		out = "…" + string(r[len(r)-1600:])
	}
	return out
}

func (e *Engine) restartRequested() bool {
	p := filepath.Join(e.l.RuntimeDir(), "restart.request")
	if exists(p) {
		_ = os.Remove(p)
		return true
	}
	return false
}

var backoff = []time.Duration{2 * time.Second, 5 * time.Second, 15 * time.Second, 30 * time.Second, 60 * time.Second}

func (e *Engine) afterExit(ctx context.Context, cmd *exec.Cmd, werr error) {
	e.mu.Lock()
	if e.cmd != cmd { // a newer engine was already started (restart) - this exit is history
		e.mu.Unlock()
		return
	}
	if e.starting == cmd { // died while spawn() waits for it: spawn reports why (log tail), no silent restart loop
		e.cmd, e.proc = nil, nil
		e.mu.Unlock()
		return
	}
	stopping := e.stopping
	e.cmd, e.proc = nil, nil
	e.mu.Unlock()
	if stopping || ctx.Err() != nil {
		e.set(EngineStopped, "")
		return
	}
	if e.restartRequested() {
		e.logf("silnik: ponowne uruchomienie na żądanie panelu")
		_ = e.spawn(ctx)
		return
	}
	now := time.Now()
	e.mu.Lock()
	recent := e.restarts[:0]
	for _, t := range e.restarts {
		if now.Sub(t) < 10*time.Minute {
			recent = append(recent, t)
		}
	}
	e.restarts = append(recent, now)
	n := len(e.restarts)
	e.mu.Unlock()
	why := "nieoczekiwane zakończenie"
	if werr != nil {
		why += " (" + werr.Error() + ")"
	}
	if n > len(backoff) {
		e.set(EngineFailed, why+"; limit ponownych uruchomień wyczerpany – sprawdź "+filepath.Join(e.l.LogsDir(), "engine_console.log"))
		return
	}
	wait := backoff[n-1]
	e.set(EngineCrashed, fmt.Sprintf("%s; ponowne uruchomienie za %d s", why, int(wait.Seconds())))
	select {
	case <-time.After(wait):
	case <-ctx.Done():
		return
	}
	_ = e.spawn(ctx)
}

// Restart from the shell (tray / start screen): stop the owned engine and start it again.
func (e *Engine) Restart(ctx context.Context) error {
	e.Stop(20 * time.Second)
	e.ResetBackoff()
	return e.Start(ctx)
}

// ResetBackoff forgets earlier crashes (the user asked for a new attempt).
func (e *Engine) ResetBackoff() {
	e.mu.Lock()
	e.restarts = nil
	e.mu.Unlock()
}

// Stop shuts an OWNED engine down (its shutdown endpoint, then a forced kill). An attached external engine is left running.
func (e *Engine) Stop(timeout time.Duration) {
	e.mu.Lock()
	cmd, exited := e.cmd, e.exited
	if cmd == nil {
		e.mu.Unlock()
		return
	}
	e.stopping = true
	e.mu.Unlock()
	if tok, err := os.ReadFile(filepath.Join(e.l.RuntimeDir(), "shutdown.token")); err == nil {
		req, _ := http.NewRequest("POST", e.URL()+"api/v1/admin/shutdown", strings.NewReader("{}"))
		req.Header.Set("x-mq-shutdown", strings.TrimSpace(string(tok)))
		req.Header.Set("Content-Type", "application/json")
		if r, err := e.client.Do(req); err == nil {
			r.Body.Close()
		}
	}
	select {
	case <-exited:
	case <-time.After(timeout):
		e.logf("silnik: brak zakończenia po " + timeout.String() + " – wymuszone zamknięcie")
		_ = cmd.Process.Kill()
		<-exited
	}
}

func (e *Engine) Owned() bool {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.cmd != nil
}
