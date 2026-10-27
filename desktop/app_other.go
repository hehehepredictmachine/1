//go:build !windows

package main

import "fmt"

// runApp outside Windows: there is no WebView2 window - the shell runs headless (development and tests only).
func runApp(l Layout, o options, logf func(string)) int {
	fmt.Println("Okno aplikacji jest dostępne tylko w Windows – tryb bez okna.")
	return runHeadless(l, o, logf)
}
