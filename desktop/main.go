package main

// PepeMarketWizardDesktop.exe - the Windows application: own window (WebView2) with the existing panel, supervision of the
// engine, tray icon, first-start setup. Other platforms build a headless variant used for development and tests.

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"runtime/debug"
)

var version = "1.25.0" // overridden by the build: -ldflags "-X main.version=..."

// appMode "studio" (-ldflags "-X main.appMode=studio") builds PepeTrainingStudio.exe from the same sources: the window supervises
// `python -m masterquo studio` (own port, own data folder data_studio, no trading engine) instead of the bot.
var appMode = "bot"

func isStudio() bool { return appMode == "studio" }

type options struct {
	autostart bool   // started by the Windows autostart entry (may start minimized to the tray)
	headless  bool   // no window: start the engine and keep it running until Ctrl+C
	importSrc string // import the data of a previous installation (folder) without asking
}

func main() {
	var o options
	showVersion := flag.Bool("version", false, "wypisz wersję")
	flag.BoolVar(&o.autostart, "autostart", false, "start z autostartu Windows")
	flag.BoolVar(&o.headless, "headless", false, "bez okna (silnik + nadzór)")
	flag.StringVar(&o.importSrc, "import", "", "folder poprzedniej instalacji do zaimportowania")
	flag.Parse()
	if *showVersion {
		fmt.Println(version)
		return
	}
	exe, err := os.Executable()
	if err == nil {
		if p, e := filepath.EvalSymlinks(exe); e == nil {
			exe = p
		}
	}
	l := detectLayout(exe, os.Getenv)
	logf := openShellLog(l)
	crashOutput(l, logf) // 1.40.3: a panic of the window (any goroutine) leaves its stack in <data>\logs\launcher_crash.txt
	logf(fmt.Sprintf("start %s (app=%s home=%s portable=%v)", version, l.AppDir, l.Home, l.Portable))
	if o.headless {
		os.Exit(runHeadless(l, o, logf))
	}
	os.Exit(runApp(l, o, logf))
}

func crashOutput(l Layout, logf func(string)) {
	if err := os.MkdirAll(l.LogsDir(), 0o755); err != nil {
		return
	}
	f, err := os.OpenFile(filepath.Join(l.LogsDir(), "launcher_crash.txt"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o644)
	if err != nil {
		return
	}
	if err := debug.SetCrashOutput(f, debug.CrashOptions{}); err != nil {
		logf("crash output: " + err.Error())
	}
	f.Close() // SetCrashOutput keeps its own duplicate of the file
}
