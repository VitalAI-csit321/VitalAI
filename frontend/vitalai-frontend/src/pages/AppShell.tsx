import { Outlet } from "react-router-dom";
import { Sidebar } from "../components/Sidebar";
import { C } from "../components/ui";

export function AppShell() {
  return (
    <div style={{ fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif", background: C.surfaceDim, minHeight: "100vh" }}>
      <Sidebar />
      <div style={{ marginLeft: 188, minHeight: "100vh" }}>
        <Outlet />
      </div>
    </div>
  );
}
