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
	// 1.45 (Apollo23 TASK 013): borderless fullscreen, adaptive UI scale and automatic entry into the panel - ON by default.
	// Missing keys keep the defaults (JSON is decoded over defaultPrefs). The Windows display resolution is never changed.
	Fullscreen bool `json:"fullscreen"`
	AutoScale  bool `json:"auto_scale"` // 1.46 (audit): reserved - no UI scaling reads it yet; the key stays (engine API desktop.py, existing prefs files)
	AutoEnter  bool `json:"auto_enter"`
}

func defaultPrefs() Prefs {
	return Prefs{CloseAction: "ask", Fullscreen: true, AutoScale: true, AutoEnter: true}
}

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
	// 1.46: the version the pre-upgrade copy (LastBackup) was made for while that version has not started yet - a failed start / "Spróbuj
	// ponownie" does not copy the data again. Additive key; older desktop_state.json files load unchanged.
	BackupVersion string `json:"backup_version,omitempty"`
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
