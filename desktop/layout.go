package main

// Folder layout of the desktop app. The program folder (EXE + bundled Python + application code) can be replaced by an update;
// user data lives outside it, in the per-user application folder, so an update or a rollback never touches it.
//
//	<program>\PepeMarketWizardDesktop.exe   this shell
//	<program>\runtime\python\python.exe     bundled CPython (official NuGet package, Windows x64)
//	<program>\runtime\wheels\               optional: dependency wheels for an offline first start
//	<program>\backend, frontend\dist, ...   the unchanged engine and panel
//	<home>\data\                            config, database, logs, models, secrets (MASTERQUO_DATA_DIR)
//	<home>\pyenv\cp313-<hash>\              dependencies installed on the first start (one folder per requirements file)
//	<home>\backups\                         copies of the data made before importing / upgrading
//
// <home> = %LOCALAPPDATA%\PepeMarketWizard. Portable mode (file portable.txt next to the EXE): <home> = the program folder.

import (
	"os"
	"path/filepath"
	"runtime"
)

type Layout struct {
	Exe        string
	AppDir     string // folder with backend\ and frontend\
	Python     string // interpreter used for the engine
	Home       string
	DataDir    string
	EnvRoot    string
	BackupsDir string
	Portable   bool
}

func (l Layout) LogsDir() string    { return filepath.Join(l.DataDir, "logs") }
func (l Layout) RuntimeDir() string { return filepath.Join(l.DataDir, "runtime") }
func (l Layout) Requirements() string {
	return filepath.Join(l.AppDir, "requirements", "requirements-win.txt")
}
func (l Layout) WheelsDir() string { return filepath.Join(l.AppDir, "runtime", "wheels") }

func exists(p string) bool { _, err := os.Stat(p); return err == nil }

// detectLayout resolves every folder from the EXE location and the environment (env is os.Getenv in production; tests inject it).
func detectLayout(exe string, env func(string) string) Layout {
	l := Layout{Exe: exe, AppDir: filepath.Dir(exe)}
	if v := env("PMW_APP_DIR"); v != "" { // development: run the shell from desktop\ against the repository
		l.AppDir = v
	}
	l.Python = filepath.Join(l.AppDir, "runtime", "python", "python.exe")
	if runtime.GOOS != "windows" {
		l.Python = filepath.Join(l.AppDir, "runtime", "python", "bin", "python3")
	}
	if v := env("PMW_PYTHON"); v != "" {
		l.Python = v
	}
	l.Portable = exists(filepath.Join(l.AppDir, "portable.txt"))
	switch {
	case env("PMW_HOME") != "":
		l.Home = env("PMW_HOME")
	case l.Portable:
		l.Home = l.AppDir
	case env("LOCALAPPDATA") != "":
		l.Home = filepath.Join(env("LOCALAPPDATA"), "PepeMarketWizard")
	default:
		l.Home = filepath.Join(env("HOME"), ".local", "share", "PepeMarketWizard")
	}
	l.DataDir = filepath.Join(l.Home, "data")
	l.EnvRoot = filepath.Join(l.Home, "pyenv")
	l.BackupsDir = filepath.Join(l.Home, "backups")
	return l
}
