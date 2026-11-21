package main

import "strings"

// 1.44.1: intro to film z dźwiękiem. WebView2 (jak Edge) domyślnie blokuje autoodtwarzanie z dźwiękiem bez kliknięcia – w oknie
// aplikacji intro ma ruszyć samo, więc przed utworzeniem okna dopisujemy --autoplay-policy do WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS
// (oficjalna zmienna WebView2; działa tylko dla procesu tej aplikacji). Gdy przeglądarka i tak zablokuje dźwięk, panel odtwarza film
// bez dźwięku (przycisk głośnika go włącza).
const webview2ArgsEnv = "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"
const autoplayArg = "--autoplay-policy=no-user-gesture-required"

// withAutoplay dopisuje autoplayArg do istniejących argumentów (bez dublowania; własne --autoplay-policy użytkownika ma pierwszeństwo).
func withAutoplay(existing string) string {
	if strings.Contains(existing, "--autoplay-policy") {
		return existing
	}
	if strings.TrimSpace(existing) == "" {
		return autoplayArg
	}
	return strings.TrimSpace(existing) + " " + autoplayArg
}
