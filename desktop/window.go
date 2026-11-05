package main

// Geometry and addresses of the two faces of the window (platform independent, covered by desktop_test.go):
//   - the launcher "JOIN THE CULT": a small fixed window, shown while the engine starts and after it is ready;
//   - the panel: after JOIN THE CULT the same window grows to 85 % of the work area of its monitor and loads the panel.

import "strings"

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
// (its own browser launcher is skipped); intro=true plays the 6 s intro of the main menu once (after JOIN THE CULT), a reload
// after an engine restart opens the panel without it.
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
