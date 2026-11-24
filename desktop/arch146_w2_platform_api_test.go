package main

// arch146 fala 2b, grupa platform_api - I0715: czyste wyjście silnika (kod 0: „Zatrzymaj Apollo23”, 04_STOP_MASTERQUO.bat,
// python -m masterquo stop) to zatrzymanie, nie awaria - powłoka nie uruchamia silnika sama ponownie. Awaria (kod != 0, zabity proces)
// nadal restartuje z backoffem, restart.request nadal restartuje od razu. Ekran „Bot zatrzymany na żądanie” reaguje wyłącznie na czysty
// stop (flaga Engine.CleanStopped), a ponowny start tylko po kliknięciu (stare sygnały „retry” są usuwane przed oczekiwaniem).

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
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
