//go:build windows

package main

import (
	"os"
	"os/exec"
	"strings"
	"syscall"
)

func initConsole() {
	k := syscall.NewLazyDLL("kernel32.dll")
	k.NewProc("SetConsoleOutputCP").Call(65001)
	k.NewProc("SetConsoleCP").Call(65001)
}

// cmd.exe parses its own command line: the whole "/c" argument is wrapped in one extra pair of quotes so paths with spaces,
// parentheses or '&' (e.g. "Nowy folder (2)") are passed unchanged.
func runScript(root, path string, args, env []string) int {
	q := `"` + path + `"`
	for _, a := range args {
		q += ` "` + a + `"`
	}
	c := exec.Command("cmd.exe")
	c.SysProcAttr = &syscall.SysProcAttr{CmdLine: `cmd.exe /d /c "` + q + `"`}
	c.Dir, c.Env = root, env
	c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
	if err := c.Run(); err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			return ee.ExitCode()
		}
		os.Stdout.WriteString("[BLAD] " + strings.TrimSpace(err.Error()) + "\n")
		return 1
	}
	return 0
}
