package main

// 1.46 arch (I0715): what the window does when the engine stops - kept free of Windows calls so it is tested on every OS.
//
// A CLEAN exit of the engine (code 0 without restart.request: „Zatrzymaj Apollo23” in the panel, 04_STOP_MASTERQUO.bat,
// python -m masterquo stop) is the user's stop: the engine is NOT started again by itself. The window shows „Bot zatrzymany na żądanie”
// and starts the engine again only after a click made AFTER that screen was shown (bootLoop(true) waiting for a fresh „retry”).
// EngineStopped caused by the shell's own Stop() (tray restart, quit, a new boot attempt) never shows that screen - Engine.CleanStopped()
// is set only by the clean-exit branch of afterExit.

type stopScreen struct {
	show      bool // show „Bot zatrzymany na żądanie” (start screen with the start button)
	abortJoin bool // the launcher waits for WEJDŹ: end that wait (WEJDŹ would lead to a dead panel)
	loop      bool // in the panel: start bootLoop(true) - it waits for a click, never boots by itself
}

func stopScreenFor(s EngineState, clean, inApp, awaiting, quitting bool) stopScreen {
	if quitting || s != EngineStopped || !clean {
		return stopScreen{}
	}
	if awaiting {
		return stopScreen{show: true, abortJoin: true}
	}
	if inApp {
		return stopScreen{show: true, loop: true}
	}
	return stopScreen{}
}

// drainSignals drops signals buffered before now (e.g. a double click on „Spróbuj ponownie” earlier): after a clean user stop only a
// click made after the stop screen appeared may start the engine again.
func drainSignals(chs ...chan struct{}) {
	for _, ch := range chs {
		for {
			select {
			case <-ch:
				continue
			default:
			}
			break
		}
	}
}
