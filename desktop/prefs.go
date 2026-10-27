package main

// Desktop preferences. The panel changes them through the engine's local API (session + CSRF + Origin checks) which writes
// <data>\desktop_prefs.json; the shell only reads the file (on window close, at start). The shell's own bookkeeping (last
// started version, import done) is in <home>\desktop_state.json.

import (
	"encoding/json"
	"os"
	"path/filepath"
	"time"
)

type Prefs struct {
	CloseAction    string `json:"close_action"` // ask | background | exit
	Autostart      bool   `json:"autostart"`
	StartMinimized bool   `json:"start_minimized"`
}

func defaultPrefs() Prefs { return Prefs{CloseAction: "ask"} }

func loadPrefs(dataDir string) Prefs {
	p := defaultPrefs()
	b, err := os.ReadFile(filepath.Join(dataDir, "desktop_prefs.json"))
	if err != nil {
		return p
	}
	if json.Unmarshal(b, &p) != nil {
		return defaultPrefs()
	}
	switch p.CloseAction {
	case "ask", "background", "exit":
	default:
		p.CloseAction = "ask"
	}
	return p
}

type State struct {
	LastVersion string     `json:"last_version,omitempty"`
	Import      *ImportLog `json:"import,omitempty"`
	FreshStart  string     `json:"fresh_start,omitempty"` // time the user chose to start without importing old data
	LastBackup  string     `json:"last_backup,omitempty"`
}

type ImportLog struct {
	Source string `json:"source"`
	At     string `json:"at"`
	Files  int    `json:"files"`
	Bytes  int64  `json:"bytes"`
}

func statePath(home string) string { return filepath.Join(home, "desktop_state.json") }

func loadState(home string) State {
	var s State
	if b, err := os.ReadFile(statePath(home)); err == nil {
		_ = json.Unmarshal(b, &s)
	}
	return s
}

func saveState(home string, s State) error {
	if err := os.MkdirAll(home, 0o755); err != nil {
		return err
	}
	b, _ := json.MarshalIndent(s, "", "  ")
	tmp := statePath(home) + ".tmp"
	if err := os.WriteFile(tmp, b, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, statePath(home))
}

func nowISO() string { return time.Now().UTC().Format(time.RFC3339) }
