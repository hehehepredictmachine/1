package main

// Data import from a previous (portable) installation and copies made before an upgrade. Source folders are only READ - nothing
// is ever moved or deleted, so the previous installation stays a working rollback point.

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// folders that are state of a running process (pid, shutdown token, instance lock) or copies themselves - never copied
var volatileDirs = map[string]bool{"runtime": true, "backups": true}

// big, re-creatable archives skipped by the pre-upgrade copy (the import copies everything except volatile state)
var bulkyDirs = map[string]bool{"logs": true, "ticks": true}

const backupMaxFile = 128 << 20 // larger single files (raw exports) are listed in the manifest instead of being copied

type copyResult struct {
	Files   int      `json:"files"`
	Bytes   int64    `json:"bytes"`
	Skipped []string `json:"skipped,omitempty"`
}

func copyFile(src, dst string, mode fs.FileMode) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
		return err
	}
	tmp := dst + ".part"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, mode.Perm()|0o200)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		os.Remove(tmp)
		return err
	}
	if err := out.Close(); err != nil {
		os.Remove(tmp)
		return err
	}
	return os.Rename(tmp, dst)
}

// copyTree copies src into dst. skipDir decides per top-level folder name; files above maxFile (0 = no limit) are skipped and listed.
func copyTree(src, dst string, skipDir func(top string) bool, maxFile int64) (copyResult, error) {
	var r copyResult
	err := filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(src, p)
		if rel == "." {
			return nil
		}
		top := strings.Split(filepath.ToSlash(rel), "/")[0]
		if d.IsDir() {
			if skipDir(top) {
				return fs.SkipDir
			}
			return os.MkdirAll(filepath.Join(dst, rel), 0o755)
		}
		if skipDir(top) || strings.HasSuffix(p, ".part") || d.Name() == "instance.lock" {
			return nil
		}
		info, err := d.Info()
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		if maxFile > 0 && info.Size() > maxFile {
			r.Skipped = append(r.Skipped, fmt.Sprintf("%s (%d MB)", filepath.ToSlash(rel), info.Size()>>20))
			return nil
		}
		if err := copyFile(p, filepath.Join(dst, rel), info.Mode()); err != nil {
			return err
		}
		r.Files++
		r.Bytes += info.Size()
		return nil
	})
	return r, err
}

// resolveOldData accepts the previous program folder (with data\) or its data folder (with config.json).
func resolveOldData(src string) (string, error) {
	src = strings.Trim(strings.TrimSpace(src), `"`)
	if src == "" {
		return "", errors.New("nie podano folderu")
	}
	for _, c := range []string{filepath.Join(src, "data"), src} {
		if exists(filepath.Join(c, "config.json")) {
			return filepath.Clean(c), nil
		}
	}
	return "", fmt.Errorf("w folderze %q nie ma danych programu (brak data\\config.json)", src)
}

// importOldData copies a previous installation's data into an EMPTY data folder (never over existing data).
func importOldData(src, dataDir string) (ImportLog, error) {
	from, err := resolveOldData(src)
	if err != nil {
		return ImportLog{}, err
	}
	if exists(filepath.Join(dataDir, "config.json")) {
		return ImportLog{}, errors.New("folder danych aplikacji nie jest pusty – import nie nadpisuje istniejących danych")
	}
	if a, b := filepath.Clean(from), filepath.Clean(dataDir); strings.EqualFold(a, b) {
		return ImportLog{}, errors.New("folder źródłowy jest folderem danych aplikacji")
	}
	r, err := copyTree(from, dataDir, func(top string) bool { return volatileDirs[top] }, 0)
	if err != nil {
		return ImportLog{}, fmt.Errorf("kopiowanie przerwane (%d plików skopiowanych, źródło bez zmian): %w", r.Files, err)
	}
	return ImportLog{Source: from, At: nowISO(), Files: r.Files, Bytes: r.Bytes}, nil
}

// findOldData lists folders that look like a previous installation's data, nearest first (prefill of the import field).
func findOldData(appDir string) []string {
	var out []string
	seen := map[string]bool{}
	add := func(p string) {
		if d, err := resolveOldData(p); err == nil && !seen[strings.ToLower(d)] {
			seen[strings.ToLower(d)] = true
			out = append(out, d)
		}
	}
	add(appDir)
	parent := filepath.Dir(appDir)
	if entries, err := os.ReadDir(parent); err == nil {
		for _, e := range entries {
			if e.IsDir() && strings.HasPrefix(strings.ToLower(e.Name()), "pepemarketwizard") {
				add(filepath.Join(parent, e.Name()))
			}
		}
	}
	return out
}

type backupManifest struct {
	Label     string `json:"label"`
	CreatedAt string `json:"created_at"`
	Source    string `json:"source"`
	copyResult
	Note string `json:"note"`
}

// backupData copies the state of the data folder before an upgrade / import into <backups>\<timestamp>_<label>.
func backupData(dataDir, backupsDir, label string) (string, error) {
	if !exists(filepath.Join(dataDir, "config.json")) {
		return "", nil // nothing to protect yet
	}
	dir := filepath.Join(backupsDir, time.Now().Format("20060102_150405")+"_"+sanitize(label))
	r, err := copyTree(dataDir, dir, func(top string) bool { return volatileDirs[top] || bulkyDirs[top] }, backupMaxFile)
	if err != nil {
		return dir, err
	}
	m := backupManifest{Label: label, CreatedAt: nowISO(), Source: dataDir, copyResult: r,
		Note: "Kopia stanu (konfiguracja, baza, sekrety, modele, raporty). Pominięte: logi, archiwum ticków, pliki > 128 MB (lista wyżej). " +
			"Przywrócenie: zamknij aplikację i skopiuj zawartość tego folderu do folderu danych."}
	b, _ := json.MarshalIndent(m, "", "  ")
	return dir, os.WriteFile(filepath.Join(dir, "BACKUP_MANIFEST.json"), b, 0o644)
}

func sanitize(s string) string {
	return strings.Map(func(r rune) rune {
		if r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '-' || r == '_' {
			return r
		}
		return '_'
	}, s)
}

var autoModes = map[string]bool{"AUTO_DEMO": true, "AUTO_LIVE": true, "DEMO_EXECUTION": true, "LIVE_EXECUTION": true}

// neutralizeImportedMode: an automatic mode carried over from another installation must not start executing by itself in the
// new app (a new installation starts in PAPER or SIGNALS). The imported config.json gets mode PAPER and a note the panel shows;
// the user picks AUTO again in Centrum sterowania, with the account confirmation. Returns the previous mode when it changed.
func neutralizeImportedMode(dataDir string) (string, error) {
	p := filepath.Join(dataDir, "config.json")
	b, err := os.ReadFile(p)
	if err != nil {
		return "", err
	}
	var raw map[string]any
	if err := json.Unmarshal(b, &raw); err != nil {
		return "", fmt.Errorf("config.json nieczytelny: %w", err)
	}
	ex, _ := raw["execution"].(map[string]any)
	if ex == nil {
		return "", nil
	}
	mode, _ := ex["mode"].(string)
	if !autoModes[mode] {
		return "", nil
	}
	ex["mode"] = "PAPER"
	ex["mode_note"] = "Dane zaimportowano z poprzedniej instalacji, w której był tryb " + mode + ". Nowa aplikacja startuje w PAPER – " +
		"wybierz tryb automatyczny ponownie w Centrum sterowania (z potwierdzeniem rachunku)."
	out, err := json.MarshalIndent(raw, "", "  ")
	if err != nil {
		return "", err
	}
	tmp := p + ".tmp"
	if err := os.WriteFile(tmp, out, 0o644); err != nil {
		return "", err
	}
	return mode, os.Rename(tmp, p)
}
