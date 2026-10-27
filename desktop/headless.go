package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"
)

type consoleUI struct{ importSrc string }

func (c consoleUI) Status(msg string)  { fmt.Println(msg) }
func (c consoleUI) Detail(line string) { fmt.Println("  ", line) }

func (c consoleUI) ChooseData(cands []string, lastErr string) (string, bool, bool) {
	// without a window there is nobody to ask: start fresh (use -import to copy a previous installation)
	fmt.Println("Znaleziono dane poprzedniej instalacji:", cands, "- start bez importu (użyj -import <folder>)")
	return "", true, true
}

func runHeadless(l Layout, o options, logf func(string)) int {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	eng := newEngine(l, "", logf, nil)
	if err := boot(ctx, l, consoleUI{}, o.importSrc, logf, eng); err != nil {
		eng.Stop(10 * time.Second)
		fmt.Fprintln(os.Stderr, "BŁĄD:", err)
		return 1
	}
	fmt.Println("Panel:", eng.URL())
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	<-sig
	cancel()
	eng.Stop(20 * time.Second)
	return 0
}
