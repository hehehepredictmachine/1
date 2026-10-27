//go:build !windows

package main

import "os/exec"

type procGuard interface{ Close() error }

func hideWindow(cmd *exec.Cmd) {}

// guardProcess: no Job Objects outside Windows (development / CI only); the headless shell stops the engine on exit itself.
func guardProcess(cmd *exec.Cmd) procGuard { return nil }
