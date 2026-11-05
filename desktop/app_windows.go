//go:build windows

package main

// The window: WebView2 with the start screen (setup, data choice, errors) and then the engine's panel. 1.32: the start screen is
// the small launcher window "JOIN THE CULT" - when the engine is ready it waits for JOIN THE CULT, then the window grows to 85 % of
// the monitor and loads the panel (main menu with the intro). One instance per Windows
// session (a second start brings the window to the front). Closing the window follows the preference from Centrum sterowania →
// Praca aplikacji: ask / keep working in the background (tray icon) / exit and stop the bot. The start screen talks to the shell
// through one bound function that only works while the start screen is shown; the panel uses the engine's protected HTTP API.

import (
	"context"
	_ "embed"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"time"
	"unsafe"

	webview2 "github.com/jchv/go-webview2"
	"github.com/jchv/go-webview2/webviewloader"
	"golang.org/x/sys/windows"
)

func init() { runtime.LockOSThread() } // the window, WebView2 and the message loop live on the main OS thread

//go:embed splash.html
var splashHTML string

//go:embed winres/icon256.png
var iconPNG []byte

//go:embed assets/launcher-scene-small.webp
var launcherScene []byte // launcher.jpg, the scene inside the gold frame (tools/cult_assets.py)

//go:embed assets/crown.webp
var launcherCrown []byte

var (
	user32                  = windows.NewLazySystemDLL("user32.dll")
	shell32                 = windows.NewLazySystemDLL("shell32.dll")
	pMessageBoxW            = user32.NewProc("MessageBoxW")
	pShowWindow             = user32.NewProc("ShowWindow")
	pSetForegroundWindow    = user32.NewProc("SetForegroundWindow")
	pSetWindowLongPtrW      = user32.NewProc("SetWindowLongPtrW")
	pCallWindowProcW        = user32.NewProc("CallWindowProcW")
	pCreatePopupMenu        = user32.NewProc("CreatePopupMenu")
	pAppendMenuW            = user32.NewProc("AppendMenuW")
	pTrackPopupMenu         = user32.NewProc("TrackPopupMenu")
	pDestroyMenu            = user32.NewProc("DestroyMenu")
	pGetCursorPos           = user32.NewProc("GetCursorPos")
	pLoadImageW             = user32.NewProc("LoadImageW")
	pRegisterWindowMessageW = user32.NewProc("RegisterWindowMessageW")
	pIsIconic               = user32.NewProc("IsIconic")
	pPostMessageW           = user32.NewProc("PostMessageW")
	pGetSystemMetrics       = user32.NewProc("GetSystemMetrics")
	pGetWindowRect          = user32.NewProc("GetWindowRect")
	pSetWindowPos           = user32.NewProc("SetWindowPos")
	pMonitorFromWindow      = user32.NewProc("MonitorFromWindow")
	pGetMonitorInfoW        = user32.NewProc("GetMonitorInfoW")
	pShellNotifyIconW       = shell32.NewProc("Shell_NotifyIconW")
	pShellExecuteW          = shell32.NewProc("ShellExecuteW")
)

const (
	wmNull          = 0x0000
	wmClose         = 0x0010
	wmEndSession    = 0x0016
	wmApp           = 0x8000
	wmTray          = wmApp + 1 // tray icon callback (WM_APP itself is go-webview2's dispatch message)
	wmLButtonUp     = 0x0202
	wmLButtonDblClk = 0x0203
	wmRButtonUp     = 0x0205
	wmContextMenu   = 0x007B

	swHide    = 0
	swShow    = 5
	swRestore = 9

	mbOK            = 0x0
	mbYesNo         = 0x4
	mbYesNoCancel   = 0x3
	mbIconError     = 0x10
	mbIconQuestion  = 0x20
	mbIconWarning   = 0x30
	mbSetForeground = 0x10000
	idYes           = 6
	idNo            = 7

	nimAdd, nimModify, nimDelete         = 0, 1, 2
	nifMessage, nifIcon, nifTip, nifInfo = 0x1, 0x2, 0x4, 0x10
	niifInfo                             = 0x1

	mfString, mfGrayed, mfSeparator = 0x0, 0x1, 0x800
	tpmRightButton, tpmReturnCmd    = 0x2, 0x100

	smCxScreen, smCyScreen = 0, 1

	monitorDefaultToNearest           = 2
	swpNoSize, swpNoZOrder, swpNoActv = 0x1, 0x4, 0x10

	iconResourceID = 1 // winres/winres.json: RT_GROUP_ICON "#1"
	mutexName      = `Local\PepeMarketWizardDesktop`
	showEventName  = `Local\PepeMarketWizardDesktop.show`
	webview2URL    = "https://developer.microsoft.com/microsoft-edge/webview2/"
)

var gwlpWndProc = ^uintptr(3) // GWLP_WNDPROC (-4)

type notifyIconData struct {
	CbSize           uint32
	HWnd             uintptr
	UID              uint32
	UFlags           uint32
	UCallbackMessage uint32
	HIcon            uintptr
	SzTip            [128]uint16
	DwState          uint32
	DwStateMask      uint32
	SzInfo           [256]uint16
	UVersion         uint32
	SzInfoTitle      [64]uint16
	DwInfoFlags      uint32
	GuidItem         windows.GUID
	HBalloonIcon     uintptr
}

func utf16p(s string) uintptr {
	p, _ := windows.UTF16PtrFromString(s)
	return uintptr(unsafe.Pointer(p))
}

func copyUTF16(dst []uint16, s string) {
	u, _ := windows.UTF16FromString(s)
	if len(u) > len(dst) {
		u = u[:len(dst)-1]
		u = append(u, 0)
	}
	copy(dst, u)
}

func messageBox(hwnd uintptr, text, caption string, flags uintptr) uintptr {
	r, _, _ := pMessageBoxW.Call(hwnd, utf16p(text), utf16p(caption), flags|mbSetForeground)
	return r
}

func shellOpen(target string) {
	_, _, _ = pShellExecuteW.Call(0, utf16p("open"), utf16p(target), 0, 0, 1)
}

type splashState struct {
	Phase      string   `json:"phase"` // progress | choose | error | ready (engine running, waiting for JOIN THE CULT)
	Message    string   `json:"message"`
	Lines      []string `json:"lines"`
	Candidates []string `json:"candidates,omitempty"`
	Error      string   `json:"error,omitempty"`
	LogPath    string   `json:"log_path"`
	DataDir    string   `json:"data_dir"`
	Version    string   `json:"version"`
	Icon       string   `json:"icon,omitempty"`
	Scene      string   `json:"scene,omitempty"` // data URLs of the launcher art - only in the answer to "state"
	Crown      string   `json:"crown,omitempty"`
}

type rect struct{ Left, Top, Right, Bottom int32 }

type monitorInfo struct {
	CbSize    uint32
	RcMonitor rect
	RcWork    rect
	DwFlags   uint32
}

type winApp struct {
	l    Layout
	o    options
	logf func(string)
	wv   webview2.WebView
	hwnd uintptr
	eng  *Engine
	icon uintptr

	ctx    context.Context
	cancel context.CancelFunc

	oldProc        uintptr
	taskbarCreated uintptr

	mu           sync.Mutex
	phase        string // splash | app
	splash       splashState
	choice       chan dataChoice
	retry        chan struct{}
	join         chan struct{} // JOIN THE CULT on the launcher
	joinAbort    chan struct{} // the engine failed while the launcher waited for JOIN
	awaiting     bool          // the launcher waits for JOIN THE CULT
	tip          string
	quitting     bool
	balloonShown bool
	appShown     bool // the panel was opened at least once (a later RUNNING = engine restarted → reload)
	booting      bool // a start / recovery loop is active
}

// ---------------------------------------------------------------- bootUI (called from the start goroutine)

func (a *winApp) Status(msg string) {
	a.mu.Lock()
	a.splash.Phase, a.splash.Message, a.splash.Error = "progress", msg, ""
	a.mu.Unlock()
	a.logf("start: " + msg)
	a.push()
}

func (a *winApp) Detail(line string) {
	a.mu.Lock()
	a.splash.Lines = append(a.splash.Lines, line)
	if n := len(a.splash.Lines); n > 8 {
		a.splash.Lines = a.splash.Lines[n-8:]
	}
	a.mu.Unlock()
	a.push()
}

func (a *winApp) ChooseData(cands []string, lastErr string) (string, bool, bool) {
	a.mu.Lock()
	a.splash.Phase, a.splash.Candidates, a.splash.Error = "choose", cands, lastErr
	a.splash.Message = "Znaleziono dane poprzedniej instalacji"
	a.mu.Unlock()
	a.push()
	a.showWindow() // a decision is needed even when started minimized
	select {
	case c := <-a.choice:
		return c.src, c.fresh, true
	case <-a.ctx.Done():
		return "", false, false
	}
}

func (a *winApp) push() {
	a.mu.Lock()
	b, _ := json.Marshal(a.splash)
	splash := a.phase == "splash"
	a.mu.Unlock()
	if splash {
		a.wv.Dispatch(func() { a.wv.Eval("window.pmwRender && window.pmwRender(" + string(b) + ")") })
	}
}

// bound as window.pmw(action, arg) - accepted only while the start screen is shown (the panel never gets shell powers)
func (a *winApp) bridge(action, arg string) (any, error) {
	a.mu.Lock()
	phase, st := a.phase, a.splash
	a.mu.Unlock()
	if phase != "splash" {
		return nil, errors.New("niedostępne poza ekranem startowym")
	}
	switch action {
	case "state":
		st.Icon = "data:image/png;base64," + base64.StdEncoding.EncodeToString(iconPNG)
		st.Scene = "data:image/webp;base64," + base64.StdEncoding.EncodeToString(launcherScene)
		st.Crown = "data:image/webp;base64," + base64.StdEncoding.EncodeToString(launcherCrown)
		return st, nil
	case "join":
		if st.Phase != "ready" {
			return nil, errors.New("silnik bota jeszcze nie jest gotowy")
		}
		select {
		case a.join <- struct{}{}:
		default:
		}
		return true, nil
	case "import", "fresh":
		select {
		case a.choice <- dataChoice{src: arg, fresh: action == "fresh"}:
		default:
		}
		return true, nil
	case "retry":
		select {
		case a.retry <- struct{}{}:
		default:
		}
		return true, nil
	case "logs":
		shellOpen(a.l.LogsDir())
		return true, nil
	case "webview_logs":
		shellOpen(a.l.Home)
		return true, nil
	case "exit":
		a.quit()
		return true, nil
	}
	return nil, errors.New("nieznana akcja")
}

// ---------------------------------------------------------------- start and engine states

// bootLoop starts the app; after an error it waits for "Spróbuj ponownie" on the start screen. waitFirst: the error is already
// shown (engine failed while the panel was open). Only one loop runs at a time.
func (a *winApp) bootLoop(waitFirst bool) {
	a.mu.Lock()
	if a.booting {
		a.mu.Unlock()
		return
	}
	a.booting = true
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		a.booting = false
		a.mu.Unlock()
	}()
	importArg := a.o.importSrc
	a.o.importSrc = ""
	for {
		if waitFirst {
			select {
			case <-a.retry:
				a.mu.Lock()
				a.splash.Lines = nil
				a.mu.Unlock()
			case <-a.ctx.Done():
				return
			}
		}
		waitFirst = true
		err := boot(a.ctx, a.l, a, importArg, a.logf, a.eng)
		importArg = ""
		if errors.Is(err, errCancelled) || a.ctx.Err() != nil {
			a.quit()
			return
		}
		if err == nil {
			if a.awaitJoin() {
				a.openApp()
				return
			}
			if a.ctx.Err() != nil {
				return
			}
			continue // the engine failed while the launcher waited: the error is shown, "Spróbuj ponownie" starts it again
		}
		a.logf("start: BŁĄD " + err.Error())
		a.showError(err.Error())
	}
}

func (a *winApp) showError(msg string) {
	a.mu.Lock()
	wasApp := a.phase == "app"
	a.phase = "splash"
	a.splash.Phase, a.splash.Error = "error", msg
	a.splash.Message = "Nie udało się uruchomić bota"
	a.mu.Unlock()
	if wasApp {
		a.wv.Dispatch(func() { a.wv.SetHtml(splashHTML) }) // the page asks for the state itself when loaded
	} else {
		a.push()
	}
	a.showWindow()
}

// readyMessage: the line under JOIN THE CULT while the engine runs.
func (a *winApp) readyMessage() string {
	if a.eng.Owned() {
		return fmt.Sprintf("silnik bota działa (port %d)", a.eng.Port())
	}
	return fmt.Sprintf("podłączono do działającego silnika (port %d)", a.eng.Port())
}

// awaitJoin: the engine is running - the launcher shows SYSTEM READY and waits for JOIN THE CULT (true), the engine failing
// meanwhile (false, the error is already shown) or the app quitting (false). The bot works in the background meanwhile.
func (a *winApp) awaitJoin() bool {
	msg := a.readyMessage() // engine calls stay outside a.mu
	a.mu.Lock()
	a.awaiting = true
	a.splash.Phase, a.splash.Error, a.splash.Message = "ready", "", msg
	a.mu.Unlock()
	defer func() {
		a.mu.Lock()
		a.awaiting = false
		a.mu.Unlock()
	}()
	for _, ch := range []chan struct{}{a.joinAbort, a.join} { // stale signals of an earlier wait are dropped first
		select {
		case <-ch:
		default:
		}
	}
	a.push()
	a.logf("start: silnik gotowy – oczekiwanie na JOIN THE CULT")
	select {
	case <-a.join:
		return true
	case <-a.joinAbort:
		return false
	case <-a.ctx.Done():
		return false
	}
}

// workArea: the work area (without the taskbar) of the monitor that shows the window.
func (a *winApp) workArea() rect {
	mon, _, _ := pMonitorFromWindow.Call(a.hwnd, monitorDefaultToNearest)
	mi := monitorInfo{CbSize: uint32(unsafe.Sizeof(monitorInfo{}))}
	if mon != 0 {
		if ok, _, _ := pGetMonitorInfoW.Call(mon, uintptr(unsafe.Pointer(&mi))); ok != 0 && mi.RcWork.Right > mi.RcWork.Left {
			return mi.RcWork
		}
	}
	sw, _, _ := pGetSystemMetrics.Call(smCxScreen)
	sh, _, _ := pGetSystemMetrics.Call(smCyScreen)
	return rect{0, 0, int32(sw), int32(sh)}
}

// resizeCentred (UI thread): client area w x h, resizable or fixed, the outer window centred in the work area.
func (a *winApp) resizeCentred(w, h int, fixed bool) {
	hint := webview2.HintNone
	if fixed {
		hint = webview2.HintFixed
	}
	a.wv.SetSize(w, h, hint)
	var r rect
	if ok, _, _ := pGetWindowRect.Call(a.hwnd, uintptr(unsafe.Pointer(&r))); ok == 0 {
		return
	}
	wa := a.workArea()
	x, y := centred(int(r.Right-r.Left), int(r.Bottom-r.Top), int(wa.Left), int(wa.Top), int(wa.Right), int(wa.Bottom))
	_, _, _ = pSetWindowPos.Call(a.hwnd, 0, uintptr(int32(x)), uintptr(int32(y)), 0, 0, swpNoSize|swpNoZOrder|swpNoActv)
}

func (a *winApp) openApp() {
	a.mu.Lock()
	a.phase, a.appShown = "app", true
	a.mu.Unlock()
	url := panelURL(a.eng.URL(), true)
	a.logf("okno: JOIN THE CULT → panel " + url)
	a.wv.Dispatch(func() {
		wa := a.workArea()
		w, h := panelSize(int(wa.Right-wa.Left), int(wa.Bottom-wa.Top))
		a.resizeCentred(w, h, false)
		a.wv.SetTitle(a.l.WindowTitle(version))
		a.wv.Navigate(url)
	})
}

func (a *winApp) onEngineState(s EngineState, detail string) {
	port := a.eng.Port()
	switch s {
	case EngineRunning:
		a.setTip(fmt.Sprintf("PepeMarketWizard – bot działa (port %d)", port))
	case EngineExternal:
		a.setTip("PepeMarketWizard – podłączono do działającego silnika")
	case EngineStarting:
		a.setTip("PepeMarketWizard – uruchamianie silnika…")
	case EngineCrashed:
		a.setTip("PepeMarketWizard – silnik zatrzymał się, ponowne uruchomienie…")
	case EngineFailed:
		a.setTip("PepeMarketWizard – silnik nie działa (szczegóły w oknie)")
	case EngineStopped:
		a.setTip("PepeMarketWizard – silnik zatrzymany")
	}
	a.mu.Lock()
	inApp, shown, quitting, awaiting := a.phase == "app", a.appShown, a.quitting, a.awaiting
	a.mu.Unlock()
	if quitting {
		return
	}
	if awaiting { // the launcher waits for JOIN THE CULT: it always tells the true state of the engine
		switch s {
		case EngineRunning, EngineExternal:
			msg := a.readyMessage()
			a.mu.Lock()
			a.splash.Phase, a.splash.Message = "ready", msg
			a.mu.Unlock()
			a.push()
		case EngineStarting, EngineCrashed:
			a.mu.Lock()
			a.splash.Phase, a.splash.Message = "progress", "Silnik bota uruchamia się ponownie…"
			a.mu.Unlock()
			a.push()
		case EngineFailed:
			a.showError(detail)
			select {
			case a.joinAbort <- struct{}{}:
			default:
			}
		}
		return
	}
	switch {
	case s == EngineRunning && inApp && shown:
		// the engine came back (restart from the panel or after a crash): its sessions are new - reload the panel (no launcher,
		// no intro: ?pmw_joined=1 and the last screen)
		url := panelURL(a.eng.URL(), false)
		a.wv.Dispatch(func() { a.wv.Navigate(url) })
	case s == EngineFailed && inApp:
		a.showError(detail)
		go a.bootLoop(true) // "Spróbuj ponownie" on the start screen starts the engine again
	}
}

// ---------------------------------------------------------------- window, close behaviour, tray

func (a *winApp) wndProc(hwnd, msg, wp, lp uintptr) uintptr {
	switch {
	case msg == wmClose:
		a.onClose()
		return 0
	case msg == wmTray:
		switch lp & 0xFFFF {
		case wmLButtonUp, wmLButtonDblClk:
			a.showWindow()
		case wmRButtonUp, wmContextMenu:
			a.trayMenu()
		}
		return 0
	case msg == wmEndSession && wp != 0: // Windows is logging off / shutting down: stop the engine properly while we can
		a.logf("okno: koniec sesji Windows – zatrzymywanie silnika")
		a.cancel()
		a.eng.Stop(10 * time.Second)
		a.removeTray()
		return 0
	case a.taskbarCreated != 0 && msg == a.taskbarCreated: // Explorer restarted - the tray icon has to be added again
		a.addTray()
	}
	r, _, _ := pCallWindowProcW.Call(a.oldProc, hwnd, msg, wp, lp)
	return r
}

func (a *winApp) onClose() {
	a.mu.Lock()
	phase := a.phase
	a.mu.Unlock()
	if phase != "app" {
		a.quit() // nothing is trading yet - closing the start screen ends the app
		return
	}
	external := false
	if s, _ := a.eng.State(); s == EngineExternal {
		external = true
	}
	switch loadPrefs(a.l.DataDir).CloseAction {
	case "background":
		a.toBackground()
	case "exit":
		a.quit()
	default:
		text := "Czy bot ma dalej działać w tle?\n\n" +
			"Tak – okno zostanie ukryte, bot pracuje dalej (ikona przy zegarze; tam też „Zamknij aplikację”).\n" +
			"Nie – zamknij aplikację i zatrzymaj bota.\n" +
			"Anuluj – wróć do okna.\n\n" +
			"Domyślne zachowanie ustawisz w Centrum sterowania → Praca aplikacji."
		if external {
			text = "Silnik bota został uruchomiony poza tą aplikacją i będzie działał dalej niezależnie od okna.\n\n" +
				"Tak – ukryj okno (ikona przy zegarze).\nNie – zamknij okno aplikacji.\nAnuluj – wróć do okna."
		}
		switch messageBox(a.hwnd, text, "PepeMarketWizard", mbYesNoCancel|mbIconQuestion) {
		case idYes:
			a.toBackground()
		case idNo:
			a.quit()
		}
	}
}

func (a *winApp) toBackground() {
	_, _, _ = pShowWindow.Call(a.hwnd, swHide)
	a.mu.Lock()
	first := !a.balloonShown
	a.balloonShown = true
	a.mu.Unlock()
	if first {
		a.balloon("PepeMarketWizard działa w tle", "Bot pracuje dalej. Kliknij ikonę, aby otworzyć okno; prawy przycisk → Zamknij aplikację.")
	}
}

func (a *winApp) showWindow() {
	a.wv.Dispatch(func() {
		if r, _, _ := pIsIconic.Call(a.hwnd); r != 0 {
			_, _, _ = pShowWindow.Call(a.hwnd, swRestore)
		} else {
			_, _, _ = pShowWindow.Call(a.hwnd, swShow)
		}
		_, _, _ = pSetForegroundWindow.Call(a.hwnd)
	})
}

// quit: hide the window, stop an engine this app started (graceful, then forced), end the message loop.
func (a *winApp) quit() {
	a.mu.Lock()
	if a.quitting {
		a.mu.Unlock()
		return
	}
	a.quitting = true
	a.mu.Unlock()
	_, _, _ = pShowWindow.Call(a.hwnd, swHide)
	a.setTip("PepeMarketWizard – zatrzymywanie bota…")
	go func() {
		a.cancel()
		if a.eng.Owned() {
			a.logf("okno: zamykanie – zatrzymywanie silnika")
			a.eng.Stop(25 * time.Second)
		}
		a.wv.Dispatch(a.wv.Terminate)
	}()
}

func (a *winApp) nid(flags uint32) *notifyIconData {
	return &notifyIconData{CbSize: uint32(unsafe.Sizeof(notifyIconData{})), HWnd: a.hwnd, UID: 1, UFlags: flags,
		UCallbackMessage: wmTray, HIcon: a.icon}
}

func (a *winApp) addTray() {
	d := a.nid(nifMessage | nifIcon | nifTip)
	a.mu.Lock()
	copyUTF16(d.SzTip[:], a.tip)
	a.mu.Unlock()
	_, _, _ = pShellNotifyIconW.Call(nimAdd, uintptr(unsafe.Pointer(d)))
}

func (a *winApp) setTip(s string) {
	a.mu.Lock()
	a.tip = s
	a.mu.Unlock()
	d := a.nid(nifTip)
	copyUTF16(d.SzTip[:], s)
	_, _, _ = pShellNotifyIconW.Call(nimModify, uintptr(unsafe.Pointer(d)))
}

func (a *winApp) balloon(title, text string) {
	d := a.nid(nifInfo)
	copyUTF16(d.SzInfoTitle[:], title)
	copyUTF16(d.SzInfo[:], text)
	d.DwInfoFlags = niifInfo
	_, _, _ = pShellNotifyIconW.Call(nimModify, uintptr(unsafe.Pointer(d)))
}

func (a *winApp) removeTray() {
	_, _, _ = pShellNotifyIconW.Call(nimDelete, uintptr(unsafe.Pointer(a.nid(0))))
}

func (a *winApp) trayMenu() {
	const (
		cmdOpen = iota + 1
		cmdRestart
		cmdLogs
		cmdQuit
	)
	m, _, _ := pCreatePopupMenu.Call()
	add := func(flags uintptr, id uintptr, text string) { _, _, _ = pAppendMenuW.Call(m, flags, id, utf16p(text)) }
	a.mu.Lock()
	inApp := a.phase == "app"
	a.mu.Unlock()
	owned := a.eng.Owned()
	add(mfString, cmdOpen, "Otwórz okno")
	restartFlags := uintptr(mfString)
	if !inApp || !owned {
		restartFlags |= mfGrayed
	}
	add(restartFlags, cmdRestart, "Uruchom ponownie silnik")
	add(mfString, cmdLogs, "Folder logów")
	add(mfSeparator, 0, "")
	if owned || !inApp {
		add(mfString, cmdQuit, "Zamknij aplikację (zatrzymaj bota)")
	} else {
		add(mfString, cmdQuit, "Zamknij aplikację (silnik uruchomiony osobno działa dalej)")
	}
	var pt struct{ X, Y int32 }
	_, _, _ = pGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
	_, _, _ = pSetForegroundWindow.Call(a.hwnd)
	cmd, _, _ := pTrackPopupMenu.Call(m, tpmReturnCmd|tpmRightButton, uintptr(pt.X), uintptr(pt.Y), 0, a.hwnd, 0)
	_, _, _ = pDestroyMenu.Call(m)
	_, _, _ = pPostMessageW.Call(a.hwnd, wmNull, 0, 0)
	switch cmd {
	case cmdOpen:
		a.showWindow()
	case cmdRestart:
		go func() {
			if err := a.eng.Restart(a.ctx); err != nil {
				a.showError(err.Error())
				a.bootLoop(true)
			}
		}()
	case cmdLogs:
		shellOpen(a.l.LogsDir())
	case cmdQuit:
		a.quit()
	}
}

// ---------------------------------------------------------------- single instance

func singleInstance() (windows.Handle, bool) {
	m, err := windows.CreateMutex(nil, false, windows.StringToUTF16Ptr(mutexName))
	if errors.Is(err, windows.ERROR_ALREADY_EXISTS) {
		if ev, e := windows.OpenEvent(windows.EVENT_MODIFY_STATE, false, windows.StringToUTF16Ptr(showEventName)); e == nil {
			_ = windows.SetEvent(ev)
			windows.CloseHandle(ev)
		}
		if m != 0 {
			windows.CloseHandle(m)
		}
		return 0, false
	}
	return m, true
}

func (a *winApp) watchShowRequests() {
	ev, err := windows.CreateEvent(nil, 0, 0, windows.StringToUTF16Ptr(showEventName))
	if err != nil {
		return
	}
	go func() {
		for {
			if r, _ := windows.WaitForSingleObject(ev, windows.INFINITE); r != windows.WAIT_OBJECT_0 {
				return
			}
			a.showWindow()
		}
	}()
}

// ---------------------------------------------------------------- entry

func runApp(l Layout, o options, logf func(string)) int {
	mutex, first := singleInstance()
	if !first {
		logf("druga kopia – pokazano okno pierwszej")
		return 0
	}
	defer windows.CloseHandle(mutex)

	if v, err := webviewloader.GetInstalledVersion(); err != nil || v == "" {
		logf(fmt.Sprintf("brak WebView2 Runtime (%v)", err))
		switch messageBox(0, "Brak składnika Microsoft Edge WebView2 Runtime, w którym działa okno aplikacji "+
			"(w Windows 11 jest wbudowany, w Windows 10 instaluje go zwykle Microsoft Edge).\n\n"+
			"Tak – otwórz stronę Microsoftu z instalatorem (Evergreen), potem uruchom aplikację ponownie.\n"+
			"Nie – uruchom bota i otwórz panel w domyślnej przeglądarce (bez ikony przy zegarze).",
			"PepeMarketWizard", mbYesNoCancel|mbIconWarning) {
		case idYes:
			shellOpen(webview2URL)
			return 0
		case idNo:
			return runBrowserFallback(l, o, logf)
		default:
			return 0
		}
	}

	ctx, cancel := context.WithCancel(context.Background())
	a := &winApp{l: l, o: o, logf: logf, ctx: ctx, cancel: cancel, phase: "splash",
		choice: make(chan dataChoice, 1), retry: make(chan struct{}, 1), join: make(chan struct{}, 1), joinAbort: make(chan struct{}, 1),
		tip: "PepeMarketWizard – uruchamianie…"}
	a.splash = splashState{Phase: "progress", Message: "Przygotowanie…", LogPath: filepath.Join(l.LogsDir(), "engine_console.log"),
		DataDir: l.DataDir, Version: version}
	a.eng = newEngine(l, "", logf, a.onEngineState)

	sw, _, _ := pGetSystemMetrics.Call(smCxScreen)
	sh, _, _ := pGetSystemMetrics.Call(smCyScreen)
	lw, lh := launcherSize(int(sw), int(sh)) // 1.32: the launcher is a small window; JOIN THE CULT grows it to 85 %
	w, h := uint(lw), uint(lh)
	_ = os.MkdirAll(l.Home, 0o755)
	wv := webview2.NewWithOptions(webview2.WebViewOptions{
		Debug:     os.Getenv("PMW_DEBUG") == "1",
		AutoFocus: true,
		DataPath:  filepath.Join(l.Home, "webview2"),
		WindowOptions: webview2.WindowOptions{
			Title: l.WindowTitle(version), Width: w, Height: h, IconId: iconResourceID, Center: true,
		},
	})
	if wv == nil {
		logf("WebView2: nie udało się utworzyć okna")
		messageBox(0, "Nie udało się utworzyć okna WebView2. Panel zostanie otwarty w domyślnej przeglądarce.", "PepeMarketWizard", mbOK|mbIconError)
		cancel()
		return runBrowserFallback(l, o, logf)
	}
	a.wv = wv
	a.hwnd = uintptr(wv.Window())
	hinst, _, _ := windows.NewLazySystemDLL("kernel32.dll").NewProc("GetModuleHandleW").Call(0)
	a.icon, _, _ = pLoadImageW.Call(hinst, iconResourceID, 1 /* IMAGE_ICON */, 16, 16, 0)
	a.taskbarCreated, _, _ = pRegisterWindowMessageW.Call(utf16p("TaskbarCreated"))
	a.oldProc, _, _ = pSetWindowLongPtrW.Call(a.hwnd, gwlpWndProc, windows.NewCallback(a.wndProc))
	wv.SetTitle(l.WindowTitle(version))
	a.resizeCentred(lw, lh, true) // the launcher is a fixed, centred window (the panel is resizable)
	_ = wv.Bind("pmw", a.bridge)
	wv.SetHtml(splashHTML)
	a.addTray()
	a.watchShowRequests()
	if o.autostart && loadPrefs(l.DataDir).StartMinimized {
		_, _, _ = pShowWindow.Call(a.hwnd, swHide)
	}

	go a.bootLoop(false)
	wv.Run()

	a.removeTray()
	a.cancel()
	if a.eng.Owned() { // the loop ended without quit() (e.g. the window was destroyed) - still stop the engine properly
		a.eng.Stop(15 * time.Second)
	}
	logf("koniec")
	return 0
}

// runBrowserFallback: no WebView2 - the engine runs and the panel opens in the default browser. The shell ends when the engine
// stops (Centrum sterowania → Zatrzymaj aplikację, or Windows shutting down).
func runBrowserFallback(l Layout, o options, logf func(string)) int {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	stopped := make(chan struct{}, 1)
	eng := newEngine(l, "", logf, func(s EngineState, _ string) {
		if s == EngineStopped || s == EngineFailed {
			select {
			case stopped <- struct{}{}:
			default:
			}
		}
	})
	if err := boot(ctx, l, fallbackUI{}, o.importSrc, logf, eng); err != nil {
		messageBox(0, "Nie udało się uruchomić bota:\n\n"+err.Error(), "PepeMarketWizard", mbOK|mbIconError)
		eng.Stop(10 * time.Second)
		return 1
	}
	shellOpen(eng.URL())
	if !eng.Owned() {
		return 0
	}
	<-stopped
	return 0
}

type fallbackUI struct{}

func (fallbackUI) Status(string) {}
func (fallbackUI) Detail(string) {}
func (fallbackUI) ChooseData(cands []string, lastErr string) (string, bool, bool) {
	if lastErr == "" && len(cands) > 0 {
		r := messageBox(0, "Znaleziono dane poprzedniej instalacji:\n"+strings.Join(cands, "\n")+
			"\n\nTak – skopiuj je (oryginał pozostaje bez zmian).\nNie – zacznij od zera.", "PepeMarketWizard", mbYesNo|mbIconQuestion)
		if r == idYes {
			return cands[0], false, true
		}
	}
	return "", true, true
}
