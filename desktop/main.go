package main

// PepeMarketWizardDesktop.exe - the Windows application: own window (WebView2) with the existing panel, supervision of the
// engine, tray icon, first-start setup. Other platforms build a headless variant used for development and tests.

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
)

var version = "1.24.0" // overridden by the build: -ldflags "-X main.version=..."

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
	logf(fmt.Sprintf("start %s (app=%s home=%s portable=%v)", version, l.AppDir, l.Home, l.Portable))
	if o.headless {
		os.Exit(runHeadless(l, o, logf))
	}
	os.Exit(runApp(l, o, logf))
}
