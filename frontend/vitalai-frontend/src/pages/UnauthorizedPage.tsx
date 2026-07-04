import { useNavigate } from "react-router-dom";
import { C } from "../components/ui";

export function UnauthorizedPage() {
  const navigate = useNavigate();
  return (
    <div style={{ minHeight: "100vh", background: C.surfaceDim, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>🔒</div>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: C.text, marginBottom: 8 }}>Access denied</h1>
        <p style={{ fontSize: 13, color: C.textMid, marginBottom: 20 }}>Your role doesn't have permission to view this page.</p>
        <button onClick={() => navigate("/dashboard")}
          style={{ padding: "9px 20px", background: C.teal, color: "#fff", border: "none", borderRadius: 6, fontSize: 13, fontWeight: 600, cursor: "pointer" }}>
          Back to dashboard
        </button>
      </div>
    </div>
  );
}
