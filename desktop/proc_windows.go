//go:build windows

package main

import (
	"os/exec"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

type procGuard interface{ Close() error }

type jobGuard struct{ h windows.Handle }

func (j *jobGuard) Close() error { return windows.CloseHandle(j.h) }

// hideWindow: child processes (engine, pip) run without a console window.
func hideWindow(cmd *exec.Cmd) {
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: windows.CREATE_NO_WINDOW}
}

// guardProcess puts the started engine into a Job Object with KILL_ON_JOB_CLOSE: when the shell ends - also by a crash or
// Task Manager - Windows ends the engine and everything it started, so no invisible bot keeps trading without its window and
// tray icon. A normal exit stops the engine gracefully first (Engine.Stop). Nil when the job cannot be set up (the engine then
// still runs; only the orphan protection is missing).
func guardProcess(cmd *exec.Cmd) procGuard {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return nil
	}
	info := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{
		BasicLimitInformation: windows.JOBOBJECT_BASIC_LIMIT_INFORMATION{LimitFlags: windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE},
	}
	if _, err := windows.SetInformationJobObject(job, windows.JobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&info)), uint32(unsafe.Sizeof(info))); err != nil {
		windows.CloseHandle(job)
		return nil
	}
	h, err := windows.OpenProcess(windows.PROCESS_SET_QUOTA|windows.PROCESS_TERMINATE, false, uint32(cmd.Process.Pid))
	if err != nil {
		windows.CloseHandle(job)
		return nil
	}
	defer windows.CloseHandle(h)
	if err := windows.AssignProcessToJobObject(job, h); err != nil {
		windows.CloseHandle(job)
		return nil
	}
	return &jobGuard{job}
}
