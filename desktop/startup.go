package main

// Start sequence shared by the window (Windows) and the headless mode: data choice on the first start, a copy of the data
// before a version change, dependencies, engine. Every step reports to the UI; nothing here switches the trading mode on.

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

type bootUI interface {
	Status(msg string)
	Detail(line string) // installer output
	// ChooseData blocks until the user decides: import from src, or start fresh. ok=false = the user closed the app.
	ChooseData(candidates []string, lastErr string) (src string, fresh bool, ok bool)
}

// dataChoiceNeeded: first start of this app (no data yet, no decision recorded) while a previous installation was found.
func dataChoiceNeeded(l Layout, st State) []string {
	if exists(filepath.Join(l.DataDir, "config.json")) || st.FreshStart != "" || st.Import != nil {
		return nil
	}
	var out []string
	for _, c := range findOldData(l.AppDir) {
		if !strings.EqualFold(filepath.Clean(c), filepath.Clean(l.DataDir)) {
			out = append(out, c)
		}
	}
	return out
}

// prepareData runs the data part of the start: import / fresh choice, then the pre-upgrade copy.
func prepareData(l Layout, st *State, ui bootUI, importArg string, logf func(string)) error {
	if err := os.MkdirAll(l.Home, 0o755); err != nil {
		return fmt.Errorf("nie można utworzyć folderu aplikacji %s: %w", l.Home, err)
	}
	imported := false
	if importArg != "" && !exists(filepath.Join(l.DataDir, "config.json")) {
		if err := doImport(l, st, importArg, logf); err != nil {
			return err
		}
		imported = true
	} else if cands := dataChoiceNeeded(l, *st); len(cands) > 0 {
		lastErr := ""
		for {
			src, fresh, ok := ui.ChooseData(cands, lastErr)
			if !ok {
				return errCancelled
			}
			if fresh {
				st.FreshStart = nowISO()
				logf("dane: start bez importu (wybór użytkownika)")
				break
			}
			ui.Status("Kopiowanie danych z " + src + " (oryginał pozostaje bez zmian)…")
			if err := doImport(l, st, src, logf); err != nil {
				lastErr = err.Error()
				continue
			}
			imported = true
			break
		}
	}
	if !imported && st.LastVersion != version && exists(filepath.Join(l.DataDir, "config.json")) {
		ui.Status("Kopia danych przed uruchomieniem wersji " + version + "…")
		dir, err := backupData(l.DataDir, l.BackupsDir, "przed_"+version)
		if err != nil {
			// a failed copy must not silently be treated as a rollback point - stop here, the data stays untouched
			return fmt.Errorf("kopia danych przed aktualizacją nie powiodła się (%v) – dane nie zostały zmienione; zwolnij miejsce na dysku i uruchom ponownie", err)
		}
		st.LastBackup = dir
		logf("dane: kopia przed aktualizacją " + dir)
	}
	return saveState(l.Home, *st)
}

var errCancelled = errors.New("przerwano przez użytkownika")

// dataChoice is the answer of the start screen: import from src, or start fresh.
type dataChoice struct {
	src   string
	fresh bool
}

func doImport(l Layout, st *State, src string, logf func(string)) error {
	il, err := importOldData(src, l.DataDir)
	if err != nil {
		return err
	}
	if prev, err := neutralizeImportedMode(l.DataDir); err != nil {
		return fmt.Errorf("dane skopiowane, ale nie udało się ustawić trybu PAPER: %w", err)
	} else if prev != "" {
		logf("dane: zaimportowany tryb " + prev + " zamieniony na PAPER (nowa instalacja nie wykonuje zleceń bez ponownego wyboru)")
	}
	st.Import = &il
	logf(fmt.Sprintf("dane: zaimportowano %d plików (%d MB) z %s", il.Files, il.Bytes>>20, il.Source))
	return nil
}

// boot prepares everything and starts (or attaches to) the engine. It can be called again with the same engine after an error.
func boot(ctx context.Context, l Layout, ui bootUI, importArg string, logf func(string), eng *Engine) error {
	st := loadState(l.Home)
	if err := prepareData(l, &st, ui, importArg, logf); err != nil {
		return err
	}
	if eng.Owned() && !eng.healthy() { // an earlier attempt left a process that never answered
		eng.Stop(10 * time.Second)
	}
	eng.ResetBackoff()
	if eng.healthy() { // already running (second shell, or started by the classic BAT launcher) - nothing to install
		ui.Status("Silnik już działa – podłączanie…")
		return eng.Start(ctx)
	}
	ui.Status("Sprawdzanie składników…")
	site, err := ensureEnv(ctx, l, ui.Status, ui.Detail)
	if err != nil {
		return err
	}
	eng.mu.Lock()
	eng.site = site
	eng.mu.Unlock()
	ui.Status("Uruchamianie silnika (pierwszy start może potrwać do minuty – migracja bazy)…")
	if err := eng.Start(ctx); err != nil {
		return err
	}
	st.LastVersion = version
	_ = saveState(l.Home, st)
	return nil
}

// shell log: <home>\desktop.log (start sequence, engine states). Nothing secret passes through the shell.
func openShellLog(l Layout) func(string) {
	_ = os.MkdirAll(l.Home, 0o755)
	p := filepath.Join(l.Home, "desktop.log")
	if st, err := os.Stat(p); err == nil && st.Size() > 5<<20 {
		_ = os.Rename(p, p+".1")
	}
	f, err := os.OpenFile(p, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	var mu sync.Mutex
	return func(s string) {
		if err != nil {
			return
		}
		mu.Lock()
		defer mu.Unlock()
		fmt.Fprintf(f, "%s %s\n", time.Now().Format("2006-01-02 15:04:05"), s)
	}
}
