//go:build windows

package main

import (
	"os"

	"golang.org/x/sys/windows"
)

// lockHeld (1.46 arch, I0846): another process holds the single-instance lock of an engine (backend __main__._single_instance_lock:
// msvcrt.locking LK_NBLCK on byte 0 of <data>\runtime\instance.lock). The file is only opened (never created); a successful trial lock of
// the same byte is released at once.
func lockHeld(p string) bool {
	f, err := os.OpenFile(p, os.O_RDWR, 0)
	if err != nil {
		return false
	}
	defer f.Close()
	h := windows.Handle(f.Fd())
	ol := new(windows.Overlapped)
	if err := windows.LockFileEx(h, windows.LOCKFILE_EXCLUSIVE_LOCK|windows.LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, ol); err != nil {
		return true
	}
	_ = windows.UnlockFileEx(h, 0, 1, 0, ol)
	return false
}
