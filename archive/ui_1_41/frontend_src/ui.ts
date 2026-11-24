// Global UI actions (open dialogs) reachable from any page without prop drilling.
import { createContext, useContext } from "react";

export const UiCtx = createContext<{ openSettings: () => void }>({ openSettings: () => undefined });
export const useUi = () => useContext(UiCtx);
