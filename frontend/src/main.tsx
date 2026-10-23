import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import CompareView from "./CompareView";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {new URLSearchParams(location.search).has("compare") ? <CompareView /> : <App />}
  </StrictMode>,
);
