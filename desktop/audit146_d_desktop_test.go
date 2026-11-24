package main

// 1.46 audit (group D_desktop) - regression tests for engine.go, migrate.go, startup.go, prefs.go, pyenv.go, window.go, app_windows.go and
// proc_windows.go. Helpers (testLayout, freePort, writeJSON, readJSON, waitState, fakeEngine, oldInstall) come from desktop_test.go.

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// sleepyPython: a stand-in for python that starts and never answers (exec: a kill hits the process itself).
func sleepyPython(t *testing.T) string {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("shell script stands in for python")
	}
	p := filepath.Join(t.TempDir(), "fakepy")
	if err := os.WriteFile(p, []byte("#!/bin/sh\nexec sleep 60\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	return p
}

type stateLog struct {
	mu sync.Mutex
	s  []EngineState
	d  []string
}

func (l *stateLog) add(s EngineState, d string) {
	l.mu.Lock()
	l.s, l.d = append(l.s, s), append(l.d, d)
	l.mu.Unlock()
}
func (l *stateLog) has(want EngineState) (bool, string) {
	l.mu.Lock()
	defer l.mu.Unlock()
	for i, s := range l.s {
		if s == want {
			return true, l.d[i]
		}
	}
	return false, ""
}

// chunk_49#5: Stop() of an engine that is still starting (restart from the tray during STARTING) is not reported as a failed start.
func TestAudit146StopDuringStartIsNotAFailure(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	l.Python = sleepyPython(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": freePort(t)}})
	var log stateLog
	e := newEngine(l, "", func(string) {}, log.add)
	res := make(chan error, 1)
	go func() { res <- e.Start(context.Background()) }()
	end := time.Now().Add(10 * time.Second)
	for !e.Owned() && time.Now().Before(end) {
		time.Sleep(50 * time.Millisecond)
	}
	if !e.Owned() {
		t.Fatal("engine process not started")
	}
	e.Stop(300 * time.Millisecond) // no shutdown token: forced kill after the timeout
	select {
	case err := <-res:
		if err == nil {
			t.Fatal("Start returned nil for an engine that never answered")
		}
	case <-time.After(10 * time.Second):
		t.Fatal("Start did not return after Stop")
	}
	if failed, d := log.has(EngineFailed); failed {
		t.Fatalf("a requested stop during start was reported as FAILED: %q", d)
	}
	if s, _ := e.State(); s == EngineFailed {
		t.Fatalf("state %v", s)
	}
}

// chunk_49#6: a start that misses the deadline is FAILED (not STARTING forever) and becomes RUNNING when the engine answers later.
func TestAudit146StartTimeoutIsFailedThenRunning(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	l.Python = sleepyPython(t)
	port := freePort(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
	old := startTimeout
	startTimeout = 1500 * time.Millisecond
	defer func() { startTimeout = old }()
	var log stateLog
	e := newEngine(l, "", func(string) {}, log.add)
	defer e.Stop(300 * time.Millisecond)
	if err := e.Start(context.Background()); err == nil || !strings.Contains(err.Error(), "nie odpowiedział") {
		t.Fatalf("Start after the deadline: %v", err)
	}
	if s, d := e.State(); s != EngineFailed || !strings.Contains(d, "engine_console.log") {
		t.Fatalf("state after the deadline = %v %q (want FAILED with the log path)", s, d)
	}
	srv, _ := fakeEngine(t, port, version, "x") // the engine finally answers
	defer srv.Close()
	if !waitState(e, EngineRunning, 8*time.Second) {
		s, _ := e.State()
		t.Fatalf("a late answer was not reported RUNNING: %v", s)
	}
}

// chunk_49#6: the console log cannot be opened - FAILED with the reason, not STARTING forever.
func TestAudit146ConsoleLogErrorIsFailed(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	l.Python = "/nonexistent/python"
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": freePort(t)}})
	if err := os.WriteFile(l.LogsDir(), []byte("a file where the logs folder belongs"), 0o644); err != nil {
		t.Fatal(err)
	}
	e := newEngine(l, "", func(string) {}, nil)
	if err := e.Start(context.Background()); err == nil {
		t.Fatal("Start without a console log succeeded")
	}
	if s, _ := e.State(); s != EngineFailed {
		t.Fatalf("state %v (want FAILED)", s)
	}
}

// chunk_49#4: the old engine closes its port first and deletes server.pid (then releases instance.lock) only after stopping its services -
// replaceOutdated must wait for that, otherwise the new engine ends with code 4.
func TestAudit146ReplaceWaitsForOldProcessExit(t *testing.T) {
	repo, _ := filepath.Abs("..")
	old := version
	version = "1.46.0"
	defer func() { version = old }()
	l := testLayout(t, repo)
	port := freePort(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
	os.MkdirAll(l.RuntimeDir(), 0o755)
	os.WriteFile(filepath.Join(l.RuntimeDir(), "shutdown.token"), []byte("tok\n"), 0o600)
	pidFile := filepath.Join(l.RuntimeDir(), "server.pid")
	os.WriteFile(pidFile, []byte(`{"pid": 1}`), 0o644)
	ln, err := net.Listen("tcp", "127.0.0.1:"+strconv.Itoa(port))
	if err != nil {
		t.Fatal(err)
	}
	mux := http.NewServeMux()
	srv := &http.Server{Handler: mux}
	mux.HandleFunc("/api/v1/health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"ok": true, "app": "PepeMarketWizard", "version": "1.45.0"})
	})
	mux.HandleFunc("/api/v1/admin/shutdown", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("x-mq-shutdown") != "tok" {
			w.WriteHeader(401)
			return
		}
		w.WriteHeader(200)
		w.(http.Flusher).Flush() // the answer leaves before the server closes (srv.Close right after WriteHeader can drop it: EOF)
		go func() {
			time.Sleep(50 * time.Millisecond)
			srv.Close() // the listener goes first (uvicorn) ...
			time.Sleep(1500 * time.Millisecond)
			os.Remove(filepath.Join(l.RuntimeDir(), "shutdown.token")) // ... rt.stop(), then the files, then the process ends
			os.Remove(pidFile)
		}()
	})
	go srv.Serve(ln)
	e := newEngine(l, "", func(m string) { t.Log(m) }, nil)
	if !e.replaceOutdated("1.45.0") {
		t.Fatal("replaceOutdated refused an engine of this folder")
	}
	if exists(pidFile) {
		t.Fatal("replaceOutdated returned while the old engine was still shutting down (server.pid present, instance.lock held)")
	}
}

// chunk_49#9: attached to an engine of another version - the warning reaches the start screen and auto_enter does not open the old panel.
func TestAudit146ForeignVersionWarningBlocksAutoEnter(t *testing.T) {
	repo, _ := filepath.Abs("..")
	old := version
	version = "1.46.0"
	defer func() { version = old }()
	l := testLayout(t, repo)
	port := freePort(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
	os.MkdirAll(l.RuntimeDir(), 0o755)
	os.WriteFile(filepath.Join(l.RuntimeDir(), "shutdown.token"), []byte("tok-ours\n"), 0o600)
	srv, _ := fakeEngine(t, port, "1.45.0", "tok-other") // another installation: the token is refused, the engine is never stopped
	defer srv.Close()
	e := newEngine(l, "", func(string) {}, nil)
	if err := e.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	w := e.AttachWarning()
	if s, _ := e.State(); s != EngineExternal || !strings.Contains(w, "1.45.0") || !strings.Contains(w, "1.46.0") {
		t.Fatalf("state %v warning %q", s, w)
	}
	if m := readyLine(false, port, w); !strings.Contains(m, "UWAGA") || !strings.Contains(m, "1.45.0") {
		t.Fatalf("start screen line without the warning: %q", m)
	}
	if autoEnter(defaultPrefs(), w) {
		t.Fatal("auto_enter opened the panel of an engine of another version")
	}
	// the same version: plain attach, auto_enter as configured
	version = "1.45.0"
	if err := e.Start(context.Background()); err != nil {
		t.Fatal(err)
	}
	if w := e.AttachWarning(); w != "" || !autoEnter(defaultPrefs(), w) {
		t.Fatalf("same version: warning %q", w)
	}
	if m := readyLine(false, port, ""); m != "podłączono do działającego silnika (port "+strconv.Itoa(port)+")" {
		t.Fatalf("plain attach line %q", m)
	}
	if m := readyLine(true, port, ""); m != "silnik bota działa (port "+strconv.Itoa(port)+")" {
		t.Fatalf("owned line %q", m)
	}
}

// chunk_49#11: the borderless fullscreen keeps a window hidden by start_minimized hidden (no WS_VISIBLE / SWP_SHOWWINDOW).
func TestAudit146FullscreenKeepsHiddenWindowHidden(t *testing.T) {
	style, swp := fullscreenFlags(false)
	if style&wsVisible != 0 || swp&swpShowWindow != 0 || style&wsPopup == 0 || swp&swpFrameChanged == 0 {
		t.Fatalf("hidden window: style %#x swp %#x", style, swp)
	}
	style, swp = fullscreenFlags(true)
	if style != wsPopup|wsVisible || swp != swpFrameChanged|swpShowWindow { // unchanged for a visible window
		t.Fatalf("visible window: style %#x swp %#x", style, swp)
	}
}

type scriptedUI struct{ choices []dataChoice }

func (s *scriptedUI) Status(string) {}
func (s *scriptedUI) Detail(string) {}
func (s *scriptedUI) ChooseData(c []string, lastErr string) (string, bool, bool) {
	if len(s.choices) == 0 {
		return "", false, false
	}
	ch := s.choices[0]
	s.choices = s.choices[1:]
	return ch.src, ch.fresh, true
}

// chunk_49#7: an interrupted import leaves no (un-neutralized) config.json in the data folder; the import can be repeated and "fresh"
// after a failed import does not start on a partial copy.
func TestAudit146InterruptedImportLeavesNoConfig(t *testing.T) {
	old := oldInstall(t, "AUTO_LIVE")
	writeJSON(t, filepath.Join(old, "data", "models", "m.json"), map[string]any{"m": 1})
	l := testLayout(t, t.TempDir())
	os.MkdirAll(l.DataDir, 0o755)
	obstacle := filepath.Join(l.DataDir, "models") // a file where the copy needs a folder: the copy breaks after config.json
	os.WriteFile(obstacle, []byte("x"), 0o644)
	st := State{}
	if err := doImport(l, &st, old, func(string) {}); err == nil {
		t.Fatal("the broken import reported success")
	}
	if exists(filepath.Join(l.DataDir, "config.json")) {
		t.Fatalf("interrupted import left config.json in the data folder: %v", readJSON(t, filepath.Join(l.DataDir, "config.json"))["execution"])
	}
	if exists(l.DataDir + ".importing") {
		t.Fatal("staging copy left behind")
	}
	os.Remove(obstacle)
	if err := doImport(l, &st, old, func(string) {}); err != nil {
		t.Fatalf("repeated import refused: %v", err)
	}
	ex := readJSON(t, filepath.Join(l.DataDir, "config.json"))["execution"].(map[string]any)
	if ex["mode"] != "PAPER" || !exists(filepath.Join(l.DataDir, "models", "m.json")) || !exists(filepath.Join(l.DataDir, "masterquo.sqlite")) {
		t.Fatalf("import after the retry: %v", ex)
	}
	if exists(l.DataDir+".importing") || exists(filepath.Join(l.DataDir, "runtime", "shutdown.token")) {
		t.Fatal("staging copy or volatile state left behind")
	}
	if b, _ := os.ReadFile(filepath.Join(old, "data", "config.json")); !strings.Contains(string(b), "AUTO_LIVE") {
		t.Fatal("the source was modified")
	}

	// the user picks "import" (fails) and then "start bez importu": no partial copy with AUTO_LIVE becomes the app's data
	parent := t.TempDir()
	app := filepath.Join(parent, "PepeMarketWizard_Desktop")
	os.MkdirAll(app, 0o755)
	prev := filepath.Join(parent, "PepeMarketWizard_KLIENT")
	writeJSON(t, filepath.Join(prev, "data", "config.json"), map[string]any{"execution": map[string]any{"mode": "AUTO_LIVE"}})
	writeJSON(t, filepath.Join(prev, "data", "models", "m.json"), map[string]any{"m": 1})
	l2 := testLayout(t, app)
	os.MkdirAll(l2.DataDir, 0o755)
	os.WriteFile(filepath.Join(l2.DataDir, "models"), []byte("x"), 0o644)
	ui := &scriptedUI{choices: []dataChoice{{src: prev}, {fresh: true}}}
	st2 := State{}
	if err := prepareData(l2, &st2, ui, "", func(string) {}); err != nil || st2.FreshStart == "" {
		t.Fatalf("fresh after a failed import: %v %+v", err, st2)
	}
	if exists(filepath.Join(l2.DataDir, "config.json")) {
		t.Fatal("start bez importu runs on the partial copy of the failed import")
	}
}

// chunk_49#8: one pre-upgrade copy per version - a failed start / "Spróbuj ponownie" does not copy the data again.
func TestAudit146BackupOncePerVersion(t *testing.T) {
	l := testLayout(t, t.TempDir())
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"a": 1})
	writeJSON(t, filepath.Join(l.Home, "desktop_state.json"), map[string]any{"last_version": "1.0.0"})
	ui := &fakeUI{}
	for i := 0; i < 2; i++ {
		if i > 0 {
			time.Sleep(1100 * time.Millisecond) // a new timestamp - HEAD made a new folder for every attempt
		}
		st := loadState(l.Home) // as boot(): the state is read again, LastVersion stays old because the start failed
		if err := prepareData(l, &st, ui, "", func(string) {}); err != nil {
			t.Fatal(err)
		}
	}
	entries, _ := os.ReadDir(l.BackupsDir)
	if len(entries) != 1 {
		names := []string{}
		for _, e := range entries {
			names = append(names, e.Name())
		}
		t.Fatalf("backups after two failed starts of the same version: %v", names)
	}
	// an older desktop_state.json (no backup_version key) still loads
	if st := loadState(l.Home); st.LastVersion != "1.0.0" || st.LastBackup == "" {
		t.Fatalf("state %+v", st)
	}
}

// chunk_49#8: a failed copy leaves no partial backup folder behind (it is no rollback point and only takes disk space).
func TestAudit146FailedBackupLeavesNoPartialCopy(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("uses a file name that only the .part suffix makes too long (Linux NAME_MAX)")
	}
	data := t.TempDir()
	writeJSON(t, filepath.Join(data, "config.json"), map[string]any{"a": 1})
	os.MkdirAll(filepath.Join(data, "models"), 0o755)
	if err := os.WriteFile(filepath.Join(data, "models", strings.Repeat("m", 252)), []byte("x"), 0o644); err != nil {
		t.Skip("file system does not take a 252-character name")
	}
	backups := filepath.Join(t.TempDir(), "backups")
	if _, err := backupData(data, backups, "przed_9.9.9"); err == nil {
		t.Fatal("the broken copy reported success")
	}
	if entries, _ := os.ReadDir(backups); len(entries) != 0 {
		t.Fatalf("partial backup left behind: %d entries", len(entries))
	}
	if !exists(filepath.Join(data, "config.json")) || !exists(filepath.Join(data, "models", strings.Repeat("m", 252))) {
		t.Fatal("the data folder was touched")
	}
}

// chunk_49#12: an output line longer than the scanner's 1 MB limit must not hang the installer step.
func TestAudit146RunLoggedDrainsLongLine(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("sh")
	}
	var lines []string
	res := make(chan error, 1)
	go func() {
		res <- runLogged(context.Background(), "sh", []string{"-c", "head -c 1100000 /dev/zero | tr '\\000' a; echo; echo done"}, nil,
			func(s string) { lines = append(lines, s) })
	}()
	select {
	case err := <-res:
		if err != nil {
			t.Fatalf("runLogged: %v", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("runLogged hangs after a line > 1 MB")
	}
}

func readSource(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(name)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// chunk_49#10: the engine's Job Object lets a separate program (Studio, started with CREATE_BREAKAWAY_FROM_JOB) outlive the engine;
// children started without that flag stay in the job (no silent breakaway).
func TestAudit146JobAllowsExplicitBreakaway(t *testing.T) {
	src := readSource(t, "proc_windows.go")
	if !strings.Contains(src, "JOB_OBJECT_LIMIT_BREAKAWAY_OK") || !strings.Contains(src, "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE") {
		t.Fatal("job limits: KILL_ON_JOB_CLOSE | BREAKAWAY_OK expected")
	}
	if strings.Contains(src, "JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK") {
		t.Fatal("silent breakaway would let every child of the engine outlive the shell")
	}
}

// chunk_49#13 / chunk_49#16: user-visible texts point to existing places and use the current product name.
func TestAudit146UserTextsCurrent(t *testing.T) {
	if strings.Contains(readSource(t, "engine.go"), "python.exe PepeMarketWizard") {
		t.Error("engine.go: old product name in the code-4 message")
	}
	if strings.Contains(readSource(t, "app_windows.go"), "Centrum sterowania → Praca aplikacji") {
		t.Error("app_windows.go: the close dialog points to the removed card Praca aplikacji")
	}
}

// focus_X5#2: the start screen state carries no unused images (launcher background / icon were base64-encoded on every "state").
func TestAudit146SplashStateWithoutDeadAssets(t *testing.T) {
	src := readSource(t, "app_windows.go")
	for _, dead := range []string{"go:embed assets/launcher-speech.webp", "go:embed winres/icon256.png", "launcherScene", "iconPNG"} {
		if strings.Contains(src, dead) {
			t.Errorf("app_windows.go still has %q", dead)
		}
	}
	if strings.Contains(readSource(t, "splash.html"), "s.scene") {
		t.Error("splash.html reads s.scene - the field is needed again")
	}
}

// chunk_49#6: a retry that already reported the late engine RUNNING is not followed by a second RUNNING from the late-start watch
// (a second RUNNING reloads the open panel).
func TestAudit146LateStartReportedOnce(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	l.Python = sleepyPython(t)
	port := freePort(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
	old := startTimeout
	startTimeout = 1500 * time.Millisecond
	defer func() { startTimeout = old }()
	var log stateLog
	e := newEngine(l, "", func(string) {}, log.add)
	defer e.Stop(300 * time.Millisecond)
	if err := e.Start(context.Background()); err == nil {
		t.Fatal("Start after the deadline succeeded")
	}
	srv, _ := fakeEngine(t, port, version, "x")
	defer srv.Close()
	if err := e.Start(context.Background()); err != nil { // "Spróbuj ponownie": our own process answers now
		t.Fatal(err)
	}
	time.Sleep(4500 * time.Millisecond) // two ticks of the watch
	log.mu.Lock()
	defer log.mu.Unlock()
	n := 0
	for _, s := range log.s {
		if s == EngineRunning {
			n++
		}
	}
	if n != 1 {
		t.Fatalf("RUNNING reported %d times: %v", n, log.s)
	}
}

// chunk_49#7: a source folder that contains the staging folder is refused before anything is removed or copied.
func TestAudit146ImportRefusesSourceAroundStaging(t *testing.T) {
	src := t.TempDir()
	writeJSON(t, filepath.Join(src, "config.json"), map[string]any{"execution": map[string]any{"mode": "PAPER"}})
	writeJSON(t, filepath.Join(src, "app", "data.importing", "keep.json"), map[string]any{"k": 1})
	if _, err := importOldData(src, filepath.Join(src, "app", "data")); err == nil {
		t.Fatal("import from a folder that contains the staging folder was accepted")
	}
	if !exists(filepath.Join(src, "app", "data.importing", "keep.json")) || !exists(filepath.Join(src, "config.json")) ||
		exists(filepath.Join(src, "app", "data")) {
		t.Fatal("the source was modified")
	}
	if within(`/a/data.importing2`, `/a/data.importing`) || !within(`/a/data.importing/x`, `/a/data.importing`) {
		t.Fatal("within")
	}
}
