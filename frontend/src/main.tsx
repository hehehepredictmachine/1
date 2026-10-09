import { createRoot } from "react-dom/client";
import App from "./App";
import { AppearanceProvider } from "./appearance";
import { StoreProvider } from "./store";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <AppearanceProvider>
    <StoreProvider>
      <App />
    </StoreProvider>
  </AppearanceProvider>,
);
