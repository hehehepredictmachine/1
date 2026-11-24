package main

import (
	"os/exec"
	"path/filepath"
	"testing"
	"time"
)

// 1.46: Stop() returned as soon as the exit channel closed, but afterExit releases the process (e.cmd = nil) only after that, so Owned()
// read right after Stop() could still be true (TestEngineSupervisorIntegration failed "engine still running after Stop" in about 1 of 3
// runs). The release is delayed here on purpose: Stop() must not return before it.
func TestAudit146StopReturnsAfterTheEngineIsReleased(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	e := newEngine(l, "", func(string) {}, nil)
	cmd := exec.Command("true")
	exited := make(chan struct{})
	close(exited) // the process has already ended ...
	e.mu.Lock()
	e.cmd, e.exited = cmd, exited
	e.mu.Unlock()
	released := make(chan time.Time, 1)
	go func() { // ... and afterExit releases it a moment later
		time.Sleep(300 * time.Millisecond)
		e.mu.Lock()
		e.cmd, e.proc = nil, nil
		e.mu.Unlock()
		released <- time.Now()
	}()
	e.Stop(5 * time.Second)
	if e.Owned() {
		t.Fatal("Stop() returned while the ended engine was still owned")
	}
	select {
	case <-released:
	case <-time.After(5 * time.Second):
		t.Fatal("release never happened")
	}
}

// A newer engine started meanwhile (restart) also ends the wait - Stop() never blocks on it.
func TestAudit146StopDoesNotWaitForANewerEngine(t *testing.T) {
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	e := newEngine(l, "", func(string) {}, nil)
	old, newer := exec.Command("true"), exec.Command("true")
	exited := make(chan struct{})
	close(exited)
	e.mu.Lock()
	e.cmd, e.exited = old, exited
	e.mu.Unlock()
	go func() {
		time.Sleep(100 * time.Millisecond)
		e.mu.Lock()
		e.cmd = newer // afterExit -> restart -> spawn
		e.mu.Unlock()
	}()
	start := time.Now()
	e.Stop(5 * time.Second)
	if d := time.Since(start); d > 2*time.Second {
		t.Fatalf("Stop() waited %v for a newer engine", d)
	}
}
