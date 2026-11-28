package main

// 1.46 arch (I0846): PepeTrainingStudio.exe is built from the same sources as the bot's shell (appMode "studio"). It used the bot's
// single-instance names, so Studio never started next to the running bot (the second app only raised the first window and quit).
// Studio now has its own names; the bot's names stay byte for byte. Because Studio and the bot can now run side by side, the Studio shell
// is isolated from the bot (mandatory conditions of the safety review):
//   - its runtime and logs folders are its own (Layout.RuntimeDir / LogsDir under <home>\data_studio): restart.request, shutdown.token,
//     engine_console.log and launcher_crash.txt of the bot are never read, consumed or appended by Studio;
//   - the dependency folder <home>\pyenv is shared - while the bot uses it (the bot answers on its port, or an installation is in
//     progress) the Studio shell never discards, reinstalls, renames or cleans it (it shows an error instead);
//   - Studio does not overwrite the bot shell's state (LastVersion / BackupVersion in <home>\desktop_state.json).

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

const (
	botMutexName     = `Local\PepeMarketWizardDesktop`
	botShowEventName = `Local\PepeMarketWizardDesktop.show`
)

// instanceNames: the single-instance mutex and the "show the first window" event of this app.
func instanceNames() (mutex, show string) {
	if isStudio() {
		return botMutexName + ".Studio", botMutexName + ".Studio.show"
	}
	return botMutexName, botShowEventName
}

// botPort: the bot engine's port from the BOT's data folder (data\config.json server.port, else 8765) - also inside the Studio shell.
func botPort(l Layout) int {
	var c struct {
		Server struct {
			Port int `json:"port"`
		} `json:"server"`
	}
	if b, err := os.ReadFile(filepath.Join(l.DataDir, "config.json")); err == nil && json.Unmarshal(b, &c) == nil && c.Server.Port >= 1024 {
		return c.Server.Port
	}
	return 8765
}

// botUsesSharedEnv: a dependency installation is in progress (a *.installing folder), the bot's engine process holds its
// single-instance lock (<bot data>\runtime\instance.lock - also while it is still starting and not answering yet), or the bot answers on
// its port - then the shared dependency folder must not be touched by another shell.
func botUsesSharedEnv(l Layout, client *http.Client) (bool, string) {
	if m, _ := filepath.Glob(filepath.Join(l.EnvRoot, "*.installing")); len(m) > 0 {
		return true, "trwa instalacja składników (" + filepath.Base(m[0]) + ")"
	}
	if lockHeld(filepath.Join(l.DataDir, "runtime", "instance.lock")) { // the BOT's runtime folder (not this shell's RuntimeDir)
		return true, "działa proces bota (blokada instance.lock)"
	}
	port := botPort(l)
	r, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/api/v1/health", port))
	if err != nil {
		return false, ""
	}
	defer r.Body.Close()
	var h struct {
		OK  bool   `json:"ok"`
		App string `json:"app"`
	}
	if r.StatusCode == 200 && json.NewDecoder(r.Body).Decode(&h) == nil && h.OK && strings.EqualFold(h.App, appName) {
		return true, fmt.Sprintf("działa bot (port %d)", port)
	}
	return false, ""
}

// prepareSharedEnv: the dependency folder for the engine. Not busy: as before (cleanup of set-aside folders, install / repair). Busy
// (Studio while the bot uses the folder): read only - a ready and intact folder is used, anything else is an error; nothing is discarded,
// installed, renamed or removed.
func prepareSharedEnv(ctx context.Context, l Layout, progress, detail func(string), busy bool, why string) (string, error) {
	if !busy {
		cleanupBrokenEnvs(l.EnvRoot)
		return ensureEnv(ctx, l, progress, detail)
	}
	if os.Getenv("PMW_SKIP_PYENV") == "1" {
		return "", nil
	}
	dir, sum, err := envDir(l)
	if err != nil {
		return "", err
	}
	if envReady(dir, sum) {
		ok, bad := envIntact(sitePackages(dir), l.Requirements())
		if ok {
			return sitePackages(dir), nil
		}
		return "", fmt.Errorf("składniki są uszkodzone (%s), a %s – Studio nie naprawia wspólnego folderu składników w trakcie pracy bota; "+
			"zamknij bota (albo poczekaj na koniec instalacji) i uruchom Studio ponownie", bad, why)
	}
	return "", fmt.Errorf("składniki nie są jeszcze zainstalowane, a %s – Studio nie instaluje wspólnego folderu składników w trakcie pracy "+
		"bota; uruchom Studio ponownie po zakończeniu instalacji albo przy zamkniętym bocie", why)
}

// rememberSuccessfulStart: the bot shell remembers the version that started (the next version change makes its own data copy again);
// the Studio shell keeps no such state - it must not skip the bot's pre-upgrade copy.
func rememberSuccessfulStart(l Layout, st State) {
	if isStudio() {
		return
	}
	st.LastVersion, st.BackupVersion = version, "" // 1.46: the next version change makes its own copy again
	_ = saveState(l.Home, st)
}
