package main

// Geometry and addresses of the two faces of the window (platform independent, covered by desktop_test.go):
//   - the launcher "WEJDŹ": a small fixed window, shown while the engine starts and after it is ready;
//   - the panel: after WEJDŹ the same window grows to 85 % of the work area of its monitor and loads the panel.

import (
	"fmt"
	"strings"
)

// launcherSize: the small start window (client area) for a work area of sw x sh pixels.
func launcherSize(sw, sh int) (int, int) {
	w, h := 960, 660
	if sw > 0 && float64(w) > float64(sw)*0.7 {
		w = int(float64(sw) * 0.7)
	}
	if sh > 0 && float64(h) > float64(sh)*0.85 {
		h = int(float64(sh) * 0.85)
	}
	if w < 640 {
		w = 640
	}
	if h < 460 {
		h = 460
	}
	return w, h
}

// panelSize: 85 % of the work area - readable on any resolution and scaling (unchanged since 1.20).
func panelSize(sw, sh int) (int, int) {
	if sw <= 0 || sh <= 0 {
		return 1440, 900
	}
	return int(float64(sw) * 0.85), int(float64(sh) * 0.85)
}

// centred: top-left corner that centres a w x h window in the work area (left, top, right, bottom).
func centred(w, h int, left, top, right, bottom int) (int, int) {
	x := left + ((right-left)-w)/2
	y := top + ((bottom-top)-h)/2
	if x < left {
		x = left
	}
	if y < top {
		y = top
	}
	return x, y
}

// panelURL: the address of the panel opened by the launcher. ?pmw_joined=1 tells the panel that the launcher was already shown
// (its own browser launcher is skipped); intro=true plays the 6 s intro of the main menu once (after WEJDŹ), a reload
// after an engine restart opens the panel without it.
// 1.46 (audit): the current panel (frontend/src) reads neither parameter - the intro film is gated by sessionStorage only (introGate.ts) and
// the browser launcher / 3D intro are gone. Both stay as a harmless, test-pinned part of the URL (TestPanelURLSkipsBrowserLauncher).
func panelURL(base string, intro bool) string {
	if !strings.HasSuffix(base, "/") {
		base += "/"
	}
	u := base + "?pmw_joined=1"
	if intro {
		u += "#/menu?intro=1"
	}
	return u
}

// readyLine: the line under WEJDŹ while the engine runs. 1.46: attached to an engine of ANOTHER version (or another installation) - the
// warning is shown instead of a plain "podłączono" (before it went only to desktop.log while the old panel opened automatically).
func readyLine(owned bool, port int, warning string) string {
	switch {
	case warning != "":
		return fmt.Sprintf("UWAGA: %s (port %d)", warning, port)
	case owned:
		return fmt.Sprintf("silnik bota działa (port %d)", port)
	}
	return fmt.Sprintf("podłączono do działającego silnika (port %d)", port)
}

// autoEnter (1.46): auto_enter opens the panel by itself - never while attached to an engine of another version (the user reads the
// warning and decides on the start screen: WEJDŹ, or close the old engine first).
func autoEnter(p Prefs, warning string) bool { return p.AutoEnter && warning == "" }

// Window style / SetWindowPos flags of the borderless fullscreen (shared with app_windows.go).
const (
	swpFrameChanged, swpShowWindow = 0x20, 0x40
	wsPopup, wsVisible             = 0x80000000, 0x10000000
)

// fullscreenFlags (1.46): GWL_STYLE and SetWindowPos flags of the borderless fullscreen. WS_VISIBLE / SWP_SHOWWINDOW only for a window that
// is already visible: with the defaults (auto_enter + fullscreen) the panel opened by itself right after an autostart with start_minimized
// and SWP_SHOWWINDOW put the hidden window on the whole monitor at every Windows logon. A hidden window shows fullscreen when opened.
func fullscreenFlags(visible bool) (style, swp uintptr) {
	style, swp = wsPopup, swpFrameChanged
	if visible {
		style, swp = style|wsVisible, swp|swpShowWindow
	}
	return style, swp
}
