import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { RequireAuth, RedirectIfAuthed } from "./guards/RouteGuards";
import { ROLES } from "./types";

import { AppShell }         from "./pages/AppShell";
import { LoginPage }        from "./pages/LoginPage";
import { DashboardPage }    from "./pages/DashboardPage";
import { IntakePage }       from "./pages/IntakePage";
import { ConsentPage }      from "./pages/ConsentPage";
import { TriagePage }       from "./pages/TriagePage";
import { AuditPage }        from "./pages/AuditPage";
import { UnauthorizedPage } from "./pages/UnauthorizedPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<RedirectIfAuthed><LoginPage /></RedirectIfAuthed>} />
          <Route path="/unauthorized" element={<UnauthorizedPage />} />

          {/* Authenticated shell */}
          <Route element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route index element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<DashboardPage />} />

            {/* Intake — all authenticated roles (front_desk, ops_manager, admin) */}
            <Route path="/intake" element={
              <RequireAuth roles={[ROLES.FRONT_DESK, ROLES.OPS_MANAGER, ROLES.ADMIN]}>
                <IntakePage />
              </RequireAuth>
            } />

            {/* Consent — all authenticated roles */}
            <Route path="/consent" element={
              <RequireAuth roles={[ROLES.FRONT_DESK, ROLES.OPS_MANAGER, ROLES.ADMIN]}>
                <ConsentPage />
              </RequireAuth>
            } />

            {/* Triage — ops_manager and admin only */}
            <Route path="/triage" element={
              <RequireAuth roles={[ROLES.OPS_MANAGER, ROLES.ADMIN]}>
                <TriagePage />
              </RequireAuth>
            } />

            {/* Audit — admin only (matches backend require_roles(UserRole.ADMIN)) */}
            <Route path="/audit" element={
              <RequireAuth roles={[ROLES.ADMIN]}>
                <AuditPage />
              </RequireAuth>
            } />

            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
