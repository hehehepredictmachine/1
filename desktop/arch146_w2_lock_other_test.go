//go:build !windows

package main

// I0846 (arch146 fala 2b, platform_api): the Studio shell sees the bot engine's single-instance lock (flock here; on Windows
// lockcheck_windows.go uses LockFileEx against msvcrt.locking - compiled with GOOS=windows, not run natively).

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
	"time"
)

func TestStudioSeesTheBotInstanceLock(t *testing.T) {
	withAppMode(t, "studio")
	repo, _ := filepath.Abs("..")
	l := testLayout(t, repo)
	p := filepath.Join(l.DataDir, "runtime", "instance.lock")
	if lockHeld(p) || exists(p) {
		t.Fatal("no lock file: not held, and the check must not create it")
	}
	_ = os.MkdirAll(filepath.Dir(p), 0o755)
	f, err := os.OpenFile(p, os.O_CREATE|os.O_RDWR, 0o644)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if lockHeld(p) {
		t.Fatal("an unlocked file is not a running bot")
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil { // the bot's engine (__main__._single_instance_lock)
		t.Fatal(err)
	}
	if !lockHeld(p) {
		t.Fatal("the held instance.lock of the bot must be seen")
	}
	if busy, why := botUsesSharedEnv(l, &http.Client{Timeout: time.Second}); !busy || !strings.Contains(why, "instance.lock") {
		t.Fatalf("a starting bot (lock held, not answering yet) must block Studio's repairs: %v %q", busy, why)
	}
	_ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	if lockHeld(p) {
		t.Fatal("a released lock is not held")
	}
}
