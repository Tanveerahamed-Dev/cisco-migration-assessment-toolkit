import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./core/tokens.css";
import "./app/shell.css";

const el = document.getElementById("root");
if (!el) throw new Error("#root missing from index.html");

createRoot(el).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
