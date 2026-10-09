import { createRoot } from "react-dom/client";
import App from "./App";
import { AppearanceProvider } from "./appearance";
import { StoreProvider } from "./store";
import { ThemeProvider } from "./theme";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <AppearanceProvider>
      <StoreProvider>
        <App />
      </StoreProvider>
    </AppearanceProvider>
  </ThemeProvider>,
);
