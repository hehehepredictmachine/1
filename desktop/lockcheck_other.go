//go:build !windows

package main

import (
	"os"
	"syscall"
)

// lockHeld (1.46 arch, I0846): another process holds the single-instance lock of an engine (backend __main__._single_instance_lock:
// fcntl.flock LOCK_EX on <data>\runtime\instance.lock). The file is only opened (never created) and released at once.
func lockHeld(p string) bool {
	f, err := os.OpenFile(p, os.O_RDWR, 0)
	if err != nil {
		return false
	}
	defer f.Close()
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return true
	}
	_ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	return false
}
