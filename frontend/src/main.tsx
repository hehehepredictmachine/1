import { createRoot } from "react-dom/client";
import App, { CINEMATIC_START } from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import BootScreen from "./features/galaxy/BootScreen";
import { AppearanceProvider } from "./appearance";
import { StoreProvider } from "./store";
import { ThemeProvider } from "./theme";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <AppearanceProvider>
      <StoreProvider>
        <ErrorBoundary>
          <App />
        </ErrorBoundary>
      </StoreProvider>
    </AppearanceProvider>
    {!CINEMATIC_START && <BootScreen />}
  </ThemeProvider>,
);
