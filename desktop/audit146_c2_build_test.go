package main

// 1.46 audit (group C2_build) - focus_X5#8: the window of PepeTrainingStudio.exe carries the display name Apollo23 (as the bot window and
// the studio backend, masterquo/studio/app.py DISPLAY_NAME), not the old "Pepe Data & Training Studio". Exe names, the studio app id
// "PepeTrainingStudio" of /api/studio/health and the mutex are unchanged.

import (
	"strings"
	"testing"
)

func TestStudioWindowTitleUsesDisplayName(t *testing.T) {
	old := appMode
	defer func() { appMode = old }()
	l := Layout{AppDir: t.TempDir()}

	appMode = "studio"
	if got := l.WindowTitle("1.46.0"); got != "Apollo23 Data & Training Studio 1.46.0" {
		t.Fatalf("studio title %q", got)
	}
	if strings.Contains(l.WindowTitle("1.46.0"), "Pepe") {
		t.Fatal("studio title still carries the old product name")
	}
	if expectedApp() != "PepeTrainingStudio" {
		t.Fatal("studio app id must stay PepeTrainingStudio")
	}

	appMode = "bot"
	if got := l.WindowTitle("1.46.0"); got != "Apollo23 1.46.0" {
		t.Fatalf("bot title %q", got)
	}
}
