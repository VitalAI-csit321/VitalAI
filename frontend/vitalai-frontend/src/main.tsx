import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { useAuthStore } from "./store/authStore";
import { getMe } from "./api/auth";

// On boot: if a token is stored, revalidate it against /api/v1/auth/me
// The 401 interceptor in client.ts handles expiry automatically
const { token, setAuth, clearAuth } = useAuthStore.getState();
if (token) {
  getMe()
    .then(user => setAuth(token, user))
    .catch(() => clearAuth());
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
