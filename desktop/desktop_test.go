package main

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func envOf(m map[string]string) func(string) string { return func(k string) string { return m[k] } }

func writeJSON(t *testing.T, p string, v any) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(v)
	if err := os.WriteFile(p, b, 0o644); err != nil {
		t.Fatal(err)
	}
}

func readJSON(t *testing.T, p string) map[string]any {
	t.Helper()
	b, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func TestLayoutDefaultsAndOverrides(t *testing.T) {
	app := t.TempDir()
	exe := filepath.Join(app, "PepeMarketWizardDesktop.exe")
	l := detectLayout(exe, envOf(map[string]string{"LOCALAPPDATA": "/lad"}))
	if l.AppDir != app || l.Home != filepath.Join("/lad", "PepeMarketWizard") || l.DataDir != filepath.Join(l.Home, "data") || l.Portable {
		t.Fatalf("unexpected layout %+v", l)
	}
	if !strings.HasPrefix(l.Python, filepath.Join(app, "runtime", "python")) {
		t.Fatalf("python outside the bundle: %s", l.Python)
	}
	// portable: data next to the program
	os.WriteFile(filepath.Join(app, "portable.txt"), []byte("1"), 0o644)
	l = detectLayout(exe, envOf(map[string]string{"LOCALAPPDATA": "/lad"}))
	if !l.Portable || l.Home != app {
		t.Fatalf("portable layout %+v", l)
	}
	l = detectLayout(exe, envOf(map[string]string{"PMW_HOME": "/h", "PMW_PYTHON": "/py", "PMW_APP_DIR": "/repo"}))
	if l.Home != "/h" || l.Python != "/py" || l.AppDir != "/repo" || l.Requirements() != filepath.Join("/repo", "requirements", "requirements-win.txt") {
		t.Fatalf("overrides %+v", l)
	}
}

func TestPipArgsAreHashPinnedBinaryOnly(t *testing.T) {
	l := Layout{AppDir: "/app"}
	a := strings.Join(pipArgs(l, "/env", false), " ")
	for _, want := range []string{"--require-hashes", "--only-binary=:all:", "--no-deps", "--target " + filepath.Join("/env", "site-packages"), "-r " + l.Requirements()} {
		if !strings.Contains(a, want) {
			t.Fatalf("missing %q in %s", want, a)
		}
	}
	if strings.Contains(a, "--no-index") {
		t.Fatal("online install must not use --no-index")
	}
	off := strings.Join(pipArgs(l, "/env", true), " ")
	if !strings.Contains(off, "--no-index --find-links "+l.WheelsDir()) {
		t.Fatalf("offline args %s", off)
	}
}

func TestEnvDirFollowsRequirements(t *testing.T) {
	app := t.TempDir()
	l := Layout{AppDir: app, EnvRoot: filepath.Join(app, "pyenv")}
	os.MkdirAll(filepath.Join(app, "requirements"), 0o755)
	os.WriteFile(l.Requirements(), []byte("a==1 --hash=sha256:00\n"), 0o644)
	d1, sum1, err := envDir(l)
	if err != nil {
		t.Fatal(err)
	}
	if envReady(d1, sum1) {
		t.Fatal("empty folder must not be ready")
	}
	os.MkdirAll(sitePackages(d1), 0o755)
	writeJSON(t, filepath.Join(d1, "ok.json"), envMarker{ReqSHA256: sum1})
	if !envReady(d1, sum1) {
		t.Fatal("marked folder must be ready")
	}
	os.WriteFile(l.Requirements(), []byte("a==2 --hash=sha256:11\n"), 0o644)
	d2, sum2, _ := envDir(l)
	if d2 == d1 || envReady(d2, sum2) {
		t.Fatal("a changed requirements file needs a new dependency folder (the old one stays for rollback)")
	}
}

func TestPrefsDefaultsAndValidation(t *testing.T) {
	d := t.TempDir()
	if p := loadPrefs(d); p.CloseAction != "ask" || p.Autostart {
		t.Fatalf("default prefs %+v (autostart must never be on by default)", p)
	}
	writeJSON(t, filepath.Join(d, "desktop_prefs.json"), map[string]any{"close_action": "background", "autostart": true})
	if p := loadPrefs(d); p.CloseAction != "background" || !p.Autostart {
		t.Fatalf("prefs %+v", p)
	}
	writeJSON(t, filepath.Join(d, "desktop_prefs.json"), map[string]any{"close_action": "explode"})
	if p := loadPrefs(d); p.CloseAction != "ask" {
		t.Fatalf("unknown close action must fall back to ask: %+v", p)
	}
}

func oldInstall(t *testing.T, mode string) string {
	t.Helper()
	old := filepath.Join(t.TempDir(), "PepeMarketWizard_1_23")
	writeJSON(t, filepath.Join(old, "data", "config.json"), map[string]any{
		"config_version": 11, "execution": map[string]any{"mode": mode, "lock": "UNLOCKED_BY_USER"}, "server": map[string]any{"port": 8765}})
	os.WriteFile(filepath.Join(old, "data", "masterquo.sqlite"), []byte("db"), 0o644)
	os.MkdirAll(filepath.Join(old, "data", "runtime"), 0o755)
	os.WriteFile(filepath.Join(old, "data", "runtime", "shutdown.token"), []byte("x"), 0o644)
	os.WriteFile(filepath.Join(old, "data", "instance.lock"), []byte("x"), 0o644)
	return old
}

func TestImportCopiesNeverTouchesSourceAndResetsAutoMode(t *testing.T) {
	old := oldInstall(t, "AUTO_LIVE")
	before, _ := os.ReadFile(filepath.Join(old, "data", "config.json"))
	data := filepath.Join(t.TempDir(), "data")
	il, err := importOldData(old, data)
	if err != nil {
		t.Fatal(err)
	}
	if il.Files != 2 { // config + database; runtime state and the instance lock are not copied
		t.Fatalf("copied %d files", il.Files)
	}
	if exists(filepath.Join(data, "runtime", "shutdown.token")) || exists(filepath.Join(data, "instance.lock")) {
		t.Fatal("volatile state copied")
	}
	prev, err := neutralizeImportedMode(data)
	if err != nil || prev != "AUTO_LIVE" {
		t.Fatalf("neutralize: %v %q", err, prev)
	}
	ex := readJSON(t, filepath.Join(data, "config.json"))["execution"].(map[string]any)
	if ex["mode"] != "PAPER" || !strings.Contains(ex["mode_note"].(string), "AUTO_LIVE") {
		t.Fatalf("imported execution %v", ex)
	}
	after, _ := os.ReadFile(filepath.Join(old, "data", "config.json"))
	if string(before) != string(after) || !exists(filepath.Join(old, "data", "runtime", "shutdown.token")) {
		t.Fatal("the source installation was modified")
	}
	if _, err := importOldData(old, data); err == nil {
		t.Fatal("import over existing data must be refused")
	}
}

func TestNeutralizeKeepsManualModes(t *testing.T) {
	for _, mode := range []string{"PAPER", "SIGNALS"} {
		old := oldInstall(t, mode)
		data := filepath.Join(t.TempDir(), "data")
		if _, err := importOldData(old, data); err != nil {
			t.Fatal(err)
		}
		if prev, _ := neutralizeImportedMode(data); prev != "" {
			t.Fatalf("%s changed", mode)
		}
	}
}

func TestBackupSkipsBulkyAndWritesManifest(t *testing.T) {
	data := t.TempDir()
	writeJSON(t, filepath.Join(data, "config.json"), map[string]any{"a": 1})
	os.MkdirAll(filepath.Join(data, "logs"), 0o755)
	os.WriteFile(filepath.Join(data, "logs", "masterquo.log"), []byte("log"), 0o644)
	os.MkdirAll(filepath.Join(data, "models"), 0o755)
	os.WriteFile(filepath.Join(data, "models", "m.json"), []byte("{}"), 0o644)
	dir, err := backupData(data, filepath.Join(t.TempDir(), "backups"), "przed_1.24.0")
	if err != nil {
		t.Fatal(err)
	}
	if !exists(filepath.Join(dir, "config.json")) || !exists(filepath.Join(dir, "models", "m.json")) || exists(filepath.Join(dir, "logs")) {
		t.Fatal("backup content wrong")
	}
	m := readJSON(t, filepath.Join(dir, "BACKUP_MANIFEST.json"))
	if m["label"] != "przed_1.24.0" || m["files"].(float64) != 2 {
		t.Fatalf("manifest %v", m)
	}
	if d, err := backupData(t.TempDir(), t.TempDir(), "x"); d != "" || err != nil {
		t.Fatal("no data = no backup")
	}
}

type fakeUI struct {
	choice  dataChoice
	asked   int
	lastErr string
}

func (f *fakeUI) Status(string) {}
func (f *fakeUI) Detail(string) {}
func (f *fakeUI) ChooseData(c []string, lastErr string) (string, bool, bool) {
	f.asked++
	f.lastErr = lastErr
	if f.asked > 3 {
		return "", false, false
	}
	return f.choice.src, f.choice.fresh, true
}

func testLayout(t *testing.T, app string) Layout {
	home := t.TempDir()
	return Layout{AppDir: app, Home: home, DataDir: filepath.Join(home, "data"), BackupsDir: filepath.Join(home, "backups"), EnvRoot: filepath.Join(home, "pyenv")}
}

func TestPrepareDataFlows(t *testing.T) {
	logf := func(string) {}
	// 1) previous installation found next to the program: the user is asked, import copies + resets AUTO
	parent := t.TempDir()
	app := filepath.Join(parent, "PepeMarketWizard_Desktop")
	os.MkdirAll(app, 0o755)
	old := filepath.Join(parent, "PepeMarketWizard_KLIENT")
	writeJSON(t, filepath.Join(old, "data", "config.json"), map[string]any{"execution": map[string]any{"mode": "AUTO_DEMO"}})
	l := testLayout(t, app)
	ui := &fakeUI{choice: dataChoice{src: old}}
	st := State{}
	if err := prepareData(l, &st, ui, "", logf); err != nil {
		t.Fatal(err)
	}
	if ui.asked != 1 || st.Import == nil || readJSON(t, filepath.Join(l.DataDir, "config.json"))["execution"].(map[string]any)["mode"] != "PAPER" {
		t.Fatalf("import flow: asked=%d state=%+v", ui.asked, st)
	}
	// second start: no question, version differs -> copy before the upgrade
	st2 := loadState(l.Home)
	st2.LastVersion = "1.23.0"
	if err := prepareData(l, &st2, ui, "", logf); err != nil {
		t.Fatal(err)
	}
	if ui.asked != 1 || st2.LastBackup == "" || !exists(filepath.Join(st2.LastBackup, "config.json")) {
		t.Fatalf("upgrade flow: asked=%d state=%+v", ui.asked, st2)
	}
	// 2) fresh start chosen: recorded, nothing copied, not asked again
	l2 := testLayout(t, app)
	ui2 := &fakeUI{choice: dataChoice{fresh: true}}
	st3 := State{}
	if err := prepareData(l2, &st3, ui2, "", logf); err != nil || st3.FreshStart == "" || exists(filepath.Join(l2.DataDir, "config.json")) {
		t.Fatalf("fresh flow %v %+v", err, st3)
	}
	if dataChoiceNeeded(l2, loadState(l2.Home)) != nil {
		t.Fatal("asked again after a recorded decision")
	}
	// 3) a wrong folder: the error is shown and the question repeated, cancel ends the start
	l3 := testLayout(t, app)
	ui3 := &fakeUI{choice: dataChoice{src: filepath.Join(parent, "nope")}}
	if err := prepareData(l3, &State{}, ui3, "", logf); err != errCancelled || ui3.lastErr == "" {
		t.Fatalf("bad folder flow: %v %q", err, ui3.lastErr)
	}
}

// ---------------------------------------------------------------- engine supervision against the real engine (python -m masterquo)

func freePort(t *testing.T) int {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	return ln.Addr().(*net.TCPAddr).Port
}

func waitState(e *Engine, want EngineState, d time.Duration) bool {
	end := time.Now().Add(d)
	for time.Now().Before(end) {
		if s, _ := e.State(); s == want {
			return true
		}
		time.Sleep(100 * time.Millisecond)
	}
	return false
}

// PMW_IT_PYTHON=<python with the engine's dependencies> go test -run Engine -v
func TestEngineSupervisorIntegration(t *testing.T) {
	py := os.Getenv("PMW_IT_PYTHON")
	if py == "" {
		t.Skip("PMW_IT_PYTHON not set (needs a Python with the engine's dependencies)")
	}
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	l.Python = py
	port := freePort(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{
		"server": map[string]any{"port": port, "open_browser": false}, "news": map[string]any{"enabled": false},
		"clock": map[string]any{"reference_url": nil}})
	var smu sync.Mutex
	var states []EngineState
	snapshot := func() []EngineState { smu.Lock(); defer smu.Unlock(); return append([]EngineState(nil), states...) }
	e := newEngine(l, "", func(m string) { t.Log(m) }, func(s EngineState, d string) { smu.Lock(); states = append(states, s); smu.Unlock() })
	e.extra = []string{"--demo"}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := e.Start(ctx); err != nil {
		t.Fatalf("start: %v\n%s", err, tail(filepath.Join(l.LogsDir(), "engine_console.log")))
	}
	if s, _ := e.State(); s != EngineRunning || !e.Owned() || e.Port() != port {
		t.Fatalf("state after start %v owned=%v port=%d", s, e.Owned(), e.Port())
	}
	// a second supervisor attaches instead of starting a duplicate
	e2 := newEngine(l, "", func(m string) { t.Log(m) }, nil)
	if err := e2.Start(ctx); err != nil {
		t.Fatal(err)
	}
	if s, _ := e2.State(); s != EngineExternal || e2.Owned() {
		t.Fatalf("second supervisor %v", s)
	}
	e2.Stop(time.Second) // not owned: must leave the engine running
	if !e.healthy() {
		t.Fatal("stopping an attached supervisor stopped the engine")
	}

	// crash -> automatic restart (backoff 2 s)
	e.mu.Lock()
	pid := e.cmd.Process.Pid
	e.mu.Unlock()
	if p, err := os.FindProcess(pid); err == nil {
		_ = p.Kill()
	}
	if !waitState(e, EngineCrashed, 10*time.Second) || !waitState(e, EngineRunning, 120*time.Second) {
		t.Fatalf("no restart after a crash: %v", snapshot())
	}
	e.mu.Lock()
	pid2 := e.cmd.Process.Pid
	e.mu.Unlock()
	if pid2 == pid {
		t.Fatal("same process after restart")
	}

	// restart requested by the panel: restart.request + shutdown -> immediate start, no crash state
	os.MkdirAll(l.RuntimeDir(), 0o755)
	os.WriteFile(filepath.Join(l.RuntimeDir(), "restart.request"), []byte("1"), 0o644)
	n := len(snapshot())
	shutdown(t, l, port)
	end := time.Now().Add(120 * time.Second)
	for time.Now().Before(end) {
		e.mu.Lock()
		cur := e.cmd
		e.mu.Unlock()
		if cur != nil && cur.Process.Pid != pid2 && e.healthy() {
			break
		}
		time.Sleep(200 * time.Millisecond)
	}
	for _, s := range snapshot()[n:] {
		if s == EngineCrashed {
			t.Fatalf("requested restart treated as a crash: %v", snapshot()[n:])
		}
	}
	if !e.healthy() {
		t.Fatalf("not running after a requested restart: %v", snapshot()[n:])
	}

	// stop: graceful shutdown through the token, process gone, port free
	e.Stop(30 * time.Second)
	if e.Owned() || e.healthy() {
		t.Fatal("engine still running after Stop")
	}
	if !waitState(e, EngineStopped, 5*time.Second) {
		t.Fatalf("final state %v", snapshot())
	}
}

func shutdown(t *testing.T, l Layout, port int) {
	tok, err := os.ReadFile(filepath.Join(l.RuntimeDir(), "shutdown.token"))
	if err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("curl", "-s", "-X", "POST", "-H", "x-mq-shutdown: "+strings.TrimSpace(string(tok)), "-H", "Content-Type: application/json",
		"-d", "{}", "http://127.0.0.1:"+strconv.Itoa(port)+"/api/v1/admin/shutdown")
	_ = cmd.Run()
}

func tail(p string) string {
	b, _ := os.ReadFile(p)
	if len(b) > 3000 {
		b = b[len(b)-3000:]
	}
	return string(b)
}

func TestWindowTitleHasNoEdition(t *testing.T) {
	dir := t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, "edition.json"), []byte(`{"edition":"OWNER"}`), 0o644) // a leftover 1.27-1.29 file changes nothing
	if got := (Layout{AppDir: dir}).WindowTitle("1.30.0"); got != "PepeMarketWizard 1.30.0" {
		t.Fatalf("title %q", got)
	}
}

// 1.32: the launcher "JOIN THE CULT" is a small window; JOIN grows it to 85 % and opens the panel with the intro.
func TestLauncherAndPanelGeometry(t *testing.T) {
	for _, c := range []struct{ sw, sh, w, h int }{
		{1920, 1040, 960, 660}, {1366, 728, 956, 618}, {1024, 728, 716, 618}, {800, 560, 640, 476}, {0, 0, 960, 660},
	} {
		if w, h := launcherSize(c.sw, c.sh); w != c.w || h != c.h {
			t.Errorf("launcherSize(%d,%d) = %dx%d, want %dx%d", c.sw, c.sh, w, h, c.w, c.h)
		}
	}
	if w, h := panelSize(1920, 1040); w != 1632 || h != 884 {
		t.Errorf("panelSize = %dx%d", w, h)
	}
	if w, h := panelSize(0, 0); w != 1440 || h != 900 {
		t.Errorf("panelSize fallback = %dx%d", w, h)
	}
	if x, y := centred(976, 699, 0, 0, 1920, 1040); x != 472 || y != 170 {
		t.Errorf("centred = %d,%d", x, y)
	}
	if x, y := centred(976, 699, 1920, 0, 3840, 1040); x != 2392 || y != 170 { // second monitor on the right
		t.Errorf("centred (2nd monitor) = %d,%d", x, y)
	}
	if x, y := centred(3000, 2000, 0, 0, 1920, 1040); x != 0 || y != 0 { // never above / left of the work area
		t.Errorf("centred (too big) = %d,%d", x, y)
	}
}

func TestPanelURLSkipsBrowserLauncher(t *testing.T) {
	if u := panelURL("http://127.0.0.1:8765/", true); u != "http://127.0.0.1:8765/?pmw_joined=1#/menu?intro=1" {
		t.Errorf("after JOIN: %s", u)
	}
	if u := panelURL("http://127.0.0.1:8765", false); u != "http://127.0.0.1:8765/?pmw_joined=1" { // reload after an engine restart
		t.Errorf("reload: %s", u)
	}
}

func TestLauncherPageKeepsStartFunctions(t *testing.T) {
	b, err := os.ReadFile("splash.html")
	if err != nil {
		t.Fatal(err)
	}
	page := string(b)
	for _, want := range []string{"JOIN THE CULT", `id="btnJoin"`, `call("join")`, `call("state")`, `call("import"`, `call("fresh")`,
		`call("retry")`, `call("logs")`, `call("exit")`, `s.phase === "ready"`, "SYSTEM READY", "prefers-reduced-motion"} {
		if !strings.Contains(page, want) {
			t.Errorf("splash.html: missing %q", want)
		}
	}
	if strings.Contains(page, "http://") || strings.Contains(page, "https://") { // nothing is loaded from the network
		t.Error("splash.html must not load anything from the network")
	}
	for _, n := range []string{"assets/launcher-speech.webp"} {
		st, err := os.Stat(n)
		if err != nil {
			t.Fatal(err)
		}
		if st.Size() == 0 || st.Size() > 200*1024 {
			t.Errorf("%s: %d bytes (embedded in the EXE, keep it small)", n, st.Size())
		}
	}
}

func TestStudioModeLaunchesStudioWithOwnData(t *testing.T) {
	old := appMode
	appMode = "studio"
	defer func() { appMode = old }()
	home := filepath.Join(t.TempDir(), "home with space")
	l := detectLayout(filepath.Join(t.TempDir(), "PepeTrainingStudio.exe"), func(k string) string {
		if k == "PMW_HOME" {
			return home
		}
		return ""
	})
	e := newEngine(l, "", func(string) {}, nil)
	if got := strings.Join(e.args(), " "); got != "-m masterquo studio" {
		t.Fatalf("args %q", got)
	}
	env := strings.Join(e.env(), "\n")
	if !strings.Contains(env, "MQ_STUDIO_DATA_DIR="+l.StudioDir()) || !strings.Contains(env, "MASTERQUO_DATA_DIR="+l.StudioDir()) ||
		!strings.Contains(env, "MQ_BOT_DATA_DIR="+l.DataDir) {
		t.Fatalf("env %s", env)
	}
	if e.Port() != 8780 || healthPath() != "api/studio/health" || expectedApp() != "PepeTrainingStudio" {
		t.Fatal("studio port / health")
	}
	if !strings.HasPrefix(l.WindowTitle("1.33.0"), "Pepe Data & Training Studio") {
		t.Fatal("title")
	}
}

// 1.40.1: an engine that dies during start - the error carries the reason (last log lines), and no silent restart loop follows.
func TestEarlyExitShowsLogTail(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("shell script stands in for python")
	}
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	fake := filepath.Join(t.TempDir(), "fakepy")
	os.WriteFile(fake, []byte("#!/bin/sh\necho 'Traceback (most recent call last):'\necho '  File \"x.py\", line 1'\necho 'RuntimeError: boom at start' >&2\nexit 5\n"), 0o755)
	l.Python = fake
	port := freePort(t)
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
	var smu sync.Mutex
	var states []EngineState
	e := newEngine(l, "", func(m string) { t.Log(m) }, func(s EngineState, d string) { smu.Lock(); states = append(states, s); smu.Unlock() })
	err := e.Start(context.Background())
	if err == nil || !strings.Contains(err.Error(), "RuntimeError: boom at start") || !strings.Contains(err.Error(), "kod 5") {
		t.Fatalf("error without the log tail: %v", err)
	}
	time.Sleep(2500 * time.Millisecond) // the first backoff step would have restarted it by now
	smu.Lock()
	defer smu.Unlock()
	for _, s := range states {
		if s == EngineCrashed {
			t.Fatalf("early exit went into the restart loop: %v", states)
		}
	}
	if s, _ := e.State(); s != EngineFailed {
		t.Fatalf("state %v", s)
	}
}

func TestLogTailOnlyThisStart(t *testing.T) {
	p := filepath.Join(t.TempDir(), "c.log")
	os.WriteFile(p, []byte("old run line\n===== start\na\n\nb\r\nc\n"), 0o644)
	if got := logTail(p, int64(len("old run line\n")), 2); got != "b\nc" {
		t.Fatalf("%q", got)
	}
}

// fakeEngine answers /api/v1/health as PepeMarketWizard <ver> and stops on the shutdown endpoint only with the right token.
func fakeEngine(t *testing.T, port int, ver, token string) (*http.Server, chan struct{}) {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:"+strconv.Itoa(port))
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	mux := http.NewServeMux()
	srv := &http.Server{Handler: mux}
	mux.HandleFunc("/api/v1/health", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"ok": true, "app": "PepeMarketWizard", "version": ver})
	})
	mux.HandleFunc("/api/v1/admin/shutdown", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("x-mq-shutdown") != token {
			w.WriteHeader(401)
			return
		}
		w.WriteHeader(200)
		go func() { srv.Close(); close(done) }()
	})
	go srv.Serve(ln)
	return srv, done
}

// 1.40.3: an older engine of this data folder is stopped and replaced; an engine of another folder (token refused) is never stopped.
func TestOutdatedEngineIsReplacedOnlyWhenItIsOurs(t *testing.T) {
	repo, _ := filepath.Abs("..")
	old := version
	version = "1.40.3"
	defer func() { version = old }()
	for _, tc := range []struct {
		name, token string
		want        bool
	}{{"ours", "tok-ours", true}, {"foreign", "tok-other", false}} {
		l := testLayout(t, repo)
		port := freePort(t)
		writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
		os.MkdirAll(l.RuntimeDir(), 0o755)
		os.WriteFile(filepath.Join(l.RuntimeDir(), "shutdown.token"), []byte("tok-ours\n"), 0o600)
		srv, done := fakeEngine(t, port, "1.40.0", tc.token)
		e := newEngine(l, "", func(m string) { t.Log(m) }, nil)
		ok, running := e.health()
		if !ok || running != "1.40.0" {
			t.Fatalf("%s: health %v %q", tc.name, ok, running)
		}
		if got := e.replaceOutdated(running); got != tc.want {
			t.Fatalf("%s: replaceOutdated=%v want %v", tc.name, got, tc.want)
		}
		if tc.want {
			<-done
		} else {
			if ok, _ := e.health(); !ok {
				t.Fatalf("foreign engine was stopped")
			}
			srv.Close()
		}
	}
}

// 1.40.3: the bundled Python and pip never see another Python's settings of the machine.
func TestPyChildEnvDropsForeignPythonSettings(t *testing.T) {
	for k, v := range map[string]string{"PYTHONHOME": "C:\\Python39", "PYTHONPATH": "C:\\x", "PIP_REQUIRE_VIRTUALENV": "true", "PIP_USER": "1",
		"PIP_TARGET": "C:\\t", "HTTPS_PROXY": "http://proxy:8080"} {
		t.Setenv(k, v)
	}
	env := pyChildEnv("PYTHONPATH=C:\\site")
	got := map[string][]string{}
	for _, kv := range env {
		p := strings.SplitN(kv, "=", 2)
		got[strings.ToUpper(p[0])] = append(got[strings.ToUpper(p[0])], p[1])
	}
	pick := func(keys ...string) map[string][]string { // only the keys under test are ever printed
		m := map[string][]string{}
		for _, k := range keys {
			m[k] = got[k]
		}
		return m
	}
	if got["PYTHONHOME"] != nil || got["PIP_TARGET"] != nil {
		t.Fatalf("foreign settings passed: %v", pick("PYTHONHOME", "PIP_TARGET"))
	}
	hasProxy := false
	for _, v := range got["HTTPS_PROXY"] {
		hasProxy = hasProxy || v == "http://proxy:8080"
	}
	if strings.Join(got["PYTHONPATH"], ";") != "C:\\site" || strings.Join(got["PIP_REQUIRE_VIRTUALENV"], ";") != "0" ||
		strings.Join(got["PIP_USER"], ";") != "0" || !hasProxy {
		t.Fatalf("env %v", pick("PYTHONPATH", "PIP_REQUIRE_VIRTUALENV", "PIP_USER", "HTTPS_PROXY"))
	}
	l := Layout{AppDir: "/app", DataDir: "/data"}
	e := newEngine(l, "", nil, nil)
	for _, kv := range e.env() {
		if k := strings.ToUpper(strings.SplitN(kv, "=", 2)[0]); k == "PYTHONHOME" || k == "PIP_TARGET" || k == "PIP_USER" || k == "PIP_REQUIRE_VIRTUALENV" {
			t.Fatalf("engine env carries %s", strings.SplitN(kv, "=", 2)[0])
		}
	}
}

// 1.40.4: a damaged dependency folder (file of a package removed / truncated, package missing) is detected from pip's RECORD lists.
func TestEnvIntactDetectsDamagedPackages(t *testing.T) {
	site := filepath.Join(t.TempDir(), "site-packages")
	req := filepath.Join(t.TempDir(), "requirements-win.txt")
	os.WriteFile(req, []byte("# x==1 comment\nclick==8.1.8 \\\n    --hash=sha256:aa\nuvicorn==0.1 \\\n    --hash=sha256:bb\n"), 0o644)
	mk := func(rel, body string) {
		p := filepath.Join(site, filepath.FromSlash(rel))
		os.MkdirAll(filepath.Dir(p), 0o755)
		os.WriteFile(p, []byte(body), 0o644)
	}
	mk("click/__init__.py", "from .core import Argument\n")
	mk("click/core.py", "class Argument: pass\n")
	mk("click-8.1.8.dist-info/RECORD", "click/__init__.py,sha256=x,27\nclick/core.py,sha256=y,21\nclick/__pycache__/core.cpython-313.pyc,,\n"+
		"click-8.1.8.dist-info/RECORD,,\n")
	mk("uvicorn/__init__.py", "")
	mk("uvicorn-0.1.dist-info/RECORD", "uvicorn/__init__.py,sha256=z,0\n../../bin/uvicorn,sha256=q,233\nuvicorn-0.1.dist-info/RECORD,,\n")
	if ok, bad := envIntact(site, req); !ok {
		t.Fatalf("intact folder reported damaged: %s", bad)
	}
	os.Remove(filepath.Join(site, "click", "core.py")) // the user's case: ModuleNotFoundError: No module named 'click.core'
	if ok, bad := envIntact(site, req); ok || !strings.Contains(bad, "click/core.py") {
		t.Fatalf("missing click/core.py not detected: %v %q", ok, bad)
	}
	mk("click/core.py", "trunc")
	if ok, bad := envIntact(site, req); ok || !strings.Contains(bad, "uszkodzony click/core.py") {
		t.Fatalf("truncated file not detected: %v %q", ok, bad)
	}
	mk("click/core.py", "class Argument: pass\n")
	os.RemoveAll(filepath.Join(site, "uvicorn-0.1.dist-info"))
	if ok, bad := envIntact(site, req); ok || !strings.Contains(bad, "1 z 2") {
		t.Fatalf("missing package not detected: %v %q", ok, bad)
	}
}

func TestDamagedEnvIsDiscardedAndImportFailureRecognised(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "cp313-abc")
	os.MkdirAll(filepath.Join(dir, "site-packages", "click"), 0o755)
	os.WriteFile(filepath.Join(dir, "ok.json"), []byte("{}"), 0o644)
	if err := discardEnv(dir); err != nil || exists(dir) {
		t.Fatalf("discard: %v exists=%v", err, exists(dir))
	}
	msg := "silnik zakończył się podczas startu (kod 5)\n\nOstatnie linie logu:\nModuleNotFoundError: No module named 'click.core'"
	if !importFailure(errors.New(msg)) || importFailure(errors.New("port 8765 jest zajęty")) || importFailure(nil) {
		t.Fatal("importFailure")
	}
}
