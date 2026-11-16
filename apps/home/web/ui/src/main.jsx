/* The page's entry point. One classic script (see vite.config.js), so it
 * runs from file:// too. The engine's loader (client.js) and the baked
 * questions (questions.js) are already on window by the time this runs.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
