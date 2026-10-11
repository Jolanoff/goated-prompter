import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { readTheme } from "./theme.js";
import "@fontsource-variable/instrument-sans";
import "@fontsource-variable/bricolage-grotesque";
import "./styles.css";

try { document.documentElement.dataset.theme = readTheme(window.localStorage); }
catch { document.documentElement.dataset.theme = "dark"; }

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
