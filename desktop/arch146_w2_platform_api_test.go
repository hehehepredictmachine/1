package main

// arch146 fala 2b, grupa platform_api - I0715: czyste wyjście silnika (kod 0: „Zatrzymaj Apollo23”, 04_STOP_MASTERQUO.bat,
// python -m masterquo stop) to zatrzymanie, nie awaria - powłoka nie uruchamia silnika sama ponownie. Awaria (kod != 0, zabity proces)
// nadal restartuje z backoffem, restart.request nadal restartuje od razu. Ekran „Bot zatrzymany na żądanie” reaguje wyłącznie na czysty
// stop (flaga Engine.CleanStopped), a ponowny start tylko po kliknięciu (stare sygnały „retry” są usuwane przed oczekiwaniem).

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

func newTestEngine(t *testing.T) (*Engine, func() []EngineState) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	var smu sync.Mutex
	var states []EngineState
	e := newEngine(l, "", func(string) {}, func(s EngineState, d string) { smu.Lock(); states = append(states, s); smu.Unlock() })
	return e, func() []EngineState { smu.Lock(); defer smu.Unlock(); return append([]EngineState(nil), states...) }
}

func TestCleanExitIsAStopNotACrash(t *testing.T) {
	e, states := newTestEngine(t)
	cmd := &exec.Cmd{}
	e.mu.Lock()
	e.cmd = cmd
	e.mu.Unlock()
	done := make(chan struct{})
	go func() { e.afterExit(context.Background(), cmd, nil); close(done) }()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("afterExit waited for a restart backoff after a clean exit")
	}
	if s, _ := e.State(); s != EngineStopped {
		t.Fatalf("state after a clean exit = %v (want STOPPED)", s)
	}
	if !e.CleanStopped() {
		t.Fatal("a clean exit must be flagged as the user's stop")
	}
	for _, s := range states() {
		if s == EngineCrashed || s == EngineStarting {
			t.Fatalf("clean exit treated as a crash / restarted: %v", states())
		}
	}
}

func TestShellStopIsNotACleanStop(t *testing.T) {
	e, _ := newTestEngine(t)
	cmd := &exec.Cmd{}
	e.mu.Lock()
	e.cmd, e.stopping = cmd, true // Stop() of the shell (tray restart, quit)
	e.mu.Unlock()
	e.afterExit(context.Background(), cmd, nil)
	if s, _ := e.State(); s != EngineStopped || e.CleanStopped() {
		t.Fatalf("shell stop: state %v clean=%v (want STOPPED, not a clean user stop)", s, e.CleanStopped())
	}
}

func TestCrashStillRestartsWithBackoff(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	var smu sync.Mutex
	var states []EngineState
	e := newEngine(l, "", func(string) {}, func(s EngineState, d string) {
		smu.Lock()
		states = append(states, s)
		smu.Unlock()
		if s == EngineCrashed {
			cancel() // the backoff wait ends on ctx - no real spawn in the unit test
		}
	})
	cmd := &exec.Cmd{}
	e.mu.Lock()
	e.cmd = cmd
	e.mu.Unlock()
	e.afterExit(ctx, cmd, errors.New("exit status 1"))
	smu.Lock()
	defer smu.Unlock()
	if len(states) == 0 || states[len(states)-1] != EngineCrashed || e.CleanStopped() {
		t.Fatalf("a crash must still go to CRASHED (restart with backoff): %v", states)
	}
}

func TestRestartRequestStillRestartsAtOnce(t *testing.T) {
	e, states := newTestEngine(t)
	e.l.Python = filepath.Join(t.TempDir(), "no-python") // spawn fails at once: enough to see that a restart was attempted
	_ = os.MkdirAll(e.l.RuntimeDir(), 0o755)
	_ = os.MkdirAll(e.l.LogsDir(), 0o755)
	if err := os.WriteFile(filepath.Join(e.l.RuntimeDir(), "restart.request"), []byte("1"), 0o644); err != nil {
		t.Fatal(err)
	}
	cmd := &exec.Cmd{}
	e.mu.Lock()
	e.cmd = cmd
	e.mu.Unlock()
	e.afterExit(context.Background(), cmd, nil) // clean exit WITH restart.request = restart from the panel
	got := states()
	if len(got) == 0 || got[0] != EngineStarting || e.CleanStopped() {
		t.Fatalf("restart.request must restart at once (STARTING first): %v", got)
	}
}

func TestStaleRestartRequestRemovedBeforeSpawn(t *testing.T) {
	e, _ := newTestEngine(t)
	e.l.Python = filepath.Join(t.TempDir(), "no-python")
	_ = os.MkdirAll(e.l.RuntimeDir(), 0o755)
	_ = os.MkdirAll(e.l.LogsDir(), 0o755)
	p := filepath.Join(e.l.RuntimeDir(), "restart.request")
	if err := os.WriteFile(p, []byte("1"), 0o644); err != nil {
		t.Fatal(err)
	}
	e.mu.Lock()
	e.cleanStop = true
	e.mu.Unlock()
	_ = e.spawn(context.Background())
	if exists(p) {
		t.Fatal("a stale restart.request survived the start of a new engine (a later user stop would become an automatic restart)")
	}
	if e.CleanStopped() {
		t.Fatal("a new start clears the clean-stop flag")
	}
}

func TestStopScreenOnlyForTheCleanStop(t *testing.T) {
	cases := []struct {
		s                               EngineState
		clean, inApp, awaiting, quiting bool
		want                            stopScreen
	}{
		{EngineStopped, true, true, false, false, stopScreen{show: true, loop: true}},
		{EngineStopped, true, false, true, false, stopScreen{show: true, abortJoin: true}},
		{EngineStopped, false, true, false, false, stopScreen{}}, // Stop() of the shell (tray restart, quit): no stop screen
		{EngineStopped, true, true, false, true, stopScreen{}},   // quitting first
		{EngineStopped, true, false, false, false, stopScreen{}}, // launcher not waiting and not in the panel: nothing to replace
		{EngineRunning, true, true, false, false, stopScreen{}},
		{EngineFailed, true, true, false, false, stopScreen{}},
	}
	for i, c := range cases {
		if got := stopScreenFor(c.s, c.clean, c.inApp, c.awaiting, c.quiting); got != c.want {
			t.Fatalf("case %d: %+v -> %+v (want %+v)", i, c, got, c.want)
		}
	}
}

func TestStaleRetryDroppedBeforeTheStopScreenWaits(t *testing.T) {
	retry := make(chan struct{}, 1)
	retry <- struct{}{} // an earlier double click on „Spróbuj ponownie”
	drainSignals(retry)
	select {
	case <-retry:
		t.Fatal("a buffered retry would restart the engine by itself after a clean user stop")
	case <-time.After(100 * time.Millisecond):
	}
	retry <- struct{}{} // a click AFTER the screen was shown is honoured
	select {
	case <-retry:
	default:
		t.Fatal("a new click must still be delivered")
	}
}

// ------------------------------------------------------------------------------------------------------------------------- I0846
// PepeTrainingStudio.exe (same sources, appMode "studio") used the bot's single-instance names - Studio did not start next to the bot.
// Studio gets its own names; the bot's stay byte for byte. Mandatory isolation (sceptic): Studio's runtime / logs folders are its own,
// and the Studio shell never repairs / reinstalls the SHARED dependency folder while the bot uses it.

func withAppMode(t *testing.T, mode string) {
	old := appMode
	appMode = mode
	t.Cleanup(func() { appMode = old })
}

func TestStudioUsesOwnSingleInstanceNames(t *testing.T) {
	withAppMode(t, "bot")
	m, s := instanceNames()
	if m != `Local\PepeMarketWizardDesktop` || s != `Local\PepeMarketWizardDesktop.show` {
		t.Fatalf("bot names changed: %q %q", m, s)
	}
	appMode = "studio"
	sm, ss := instanceNames()
	if sm == m || ss == s || sm == ss || sm == "" || ss == "" {
		t.Fatalf("studio names must differ from the bot's: %q %q", sm, ss)
	}
}

func TestStudioShellUsesOwnRuntimeAndLogs(t *testing.T) {
	withAppMode(t, "bot")
	home := t.TempDir()
	l := Layout{AppDir: t.TempDir(), Home: home, DataDir: filepath.Join(home, "data"), EnvRoot: filepath.Join(home, "pyenv")}
	botRuntime, botLogs := l.RuntimeDir(), l.LogsDir()
	if botRuntime != filepath.Join(l.DataDir, "runtime") || botLogs != filepath.Join(l.DataDir, "logs") {
		t.Fatalf("bot folders changed: %s %s", botRuntime, botLogs)
	}
	_ = os.MkdirAll(botRuntime, 0o755)
	req := filepath.Join(botRuntime, "restart.request")
	if err := os.WriteFile(req, []byte("1"), 0o644); err != nil {
		t.Fatal(err)
	}
	appMode = "studio"
	if l.RuntimeDir() == botRuntime || l.LogsDir() == botLogs || !strings.HasPrefix(l.RuntimeDir(), l.StudioDir()) ||
		!strings.HasPrefix(l.LogsDir(), l.StudioDir()) {
		t.Fatalf("studio runtime/logs must be its own: %s %s", l.RuntimeDir(), l.LogsDir())
	}
	e := newEngine(l, "", func(string) {}, nil)
	cmd := &exec.Cmd{}
	e.mu.Lock()
	e.cmd = cmd
	e.mu.Unlock()
	e.afterExit(context.Background(), cmd, nil) // the Studio engine ends
	if !exists(req) {
		t.Fatal("the Studio shell consumed the bot's restart.request")
	}
}

func fakeBot(t *testing.T, l Layout) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/api/v1/health" {
			_, _ = w.Write([]byte(`{"ok": true, "app": "PepeMarketWizard", "version": "x"}`))
			return
		}
		http.NotFound(w, r)
	}))
	t.Cleanup(srv.Close)
	u, _ := url.Parse(srv.URL)
	port, _ := strconv.Atoi(u.Port())
	writeJSON(t, filepath.Join(l.DataDir, "config.json"), map[string]any{"server": map[string]any{"port": port}})
}

func TestStudioNeverRepairsSharedEnvWhileBotRuns(t *testing.T) {
	withAppMode(t, "studio")
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	dir, sum, err := envDir(l)
	if err != nil {
		t.Fatal(err)
	}
	_ = os.MkdirAll(sitePackages(dir), 0o755) // damaged: marked ready, packages missing
	writeJSON(t, filepath.Join(dir, "ok.json"), map[string]any{"requirements_sha256": sum})
	if !envReady(dir, sum) {
		t.Fatal("fixture: the folder must look ready (only its packages are missing)")
	}
	broken := dir + ".broken-1"
	_ = os.MkdirAll(broken, 0o755)
	client := &http.Client{Timeout: 2 * time.Second}
	if busy, _ := botUsesSharedEnv(l, client); busy {
		t.Fatal("no bot and no installation: the folder is free")
	}
	fakeBot(t, l)
	busy, why := botUsesSharedEnv(l, client)
	if !busy || why == "" {
		t.Fatal("a running bot must be detected")
	}
	site, err := prepareSharedEnv(context.Background(), l, func(string) {}, func(string) {}, busy, why)
	if err == nil || site != "" {
		t.Fatalf("Studio must refuse to repair the folder the bot uses (site %q err %v)", site, err)
	}
	if !exists(filepath.Join(dir, "ok.json")) || !exists(broken) {
		t.Fatal("Studio removed / discarded parts of the shared dependency folder while the bot runs")
	}
}

func TestStudioTreatsBotInstallationAsBusy(t *testing.T) {
	withAppMode(t, "studio")
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	dir, _, _ := envDir(l)
	_ = os.MkdirAll(dir+".installing", 0o755)
	if busy, _ := botUsesSharedEnv(l, &http.Client{Timeout: time.Second}); !busy {
		t.Fatal("an installation in progress (.installing) must block Studio's repairs")
	}
}

func TestStudioDoesNotOverwriteBotShellState(t *testing.T) {
	home := t.TempDir()
	l := Layout{Home: home}
	withAppMode(t, "bot")
	rememberSuccessfulStart(l, State{LastVersion: "old", BackupVersion: "pending"})
	if got := loadState(home); got.LastVersion != version || got.BackupVersion != "" {
		t.Fatalf("bot start must remember its version: %+v", got)
	}
	appMode = "studio"
	rememberSuccessfulStart(l, State{LastVersion: "studio-must-not-write"})
	if got := loadState(home); got.LastVersion != version {
		t.Fatalf("Studio overwrote the bot shell state: %+v", got)
	}
}
