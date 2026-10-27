package main

import (
	"context"
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"path/filepath"
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
