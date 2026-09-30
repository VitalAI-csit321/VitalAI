import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { setClinicTimeZone } from "./lib/format";
import { apiGet } from "./lib/apiClient";
import "./index.css";

// Every calendar renders clinic time. Until /health answers it is
// Australia/Sydney, the backend's default.
apiGet<{ clinic_timezone?: string }>("/health")
  .then((health) => health.clinic_timezone && setClinicTimeZone(health.clinic_timezone))
  .catch(() => {});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
