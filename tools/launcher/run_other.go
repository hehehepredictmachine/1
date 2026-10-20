//go:build !windows

package main

import (
	"os"
	"os/exec"
)

func initConsole() {}

// Non-Windows build exists only for tests of the menu logic; scripts are run with sh if present.
func runScript(root, path string, args, env []string) int {
	c := exec.Command("sh", append([]string{path}, args...)...)
	c.Dir, c.Env = root, env
	c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := c.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return ee.ExitCode()
		}
		return 1
	}
	return 0
}
