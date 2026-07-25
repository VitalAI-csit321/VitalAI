import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";

// Auth
import { LoginPage } from "./pages/LoginPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";

// Core pages (first 10 designs)
import { DashboardPage } from "./pages/DashboardPage";
import { PatientsPage } from "./pages/PatientsPage";
import { PatientOnboardingPage } from "./pages/PatientOnboardingPage";
import { ConsentQueuePage } from "./pages/ConsentQueuePage";
import { ConsentCapturePage } from "./pages/ConsentCapturePage";
import { ConsentSuccessPage } from "./pages/ConsentSuccessPage";
import { RecordsPage } from "./pages/RecordsPage";
import { InboxPage } from "./pages/InboxPage";
import { ComposePage } from "./pages/ComposePage";

// New pages (15 new designs)
import { ReviewQueuePage } from "./pages/ReviewQueuePage";
import { EscalationsPage } from "./pages/EscalationsPage";
import { AuditPage } from "./pages/AuditPage";
import { AuditEventDetailPage } from "./pages/AuditEventDetailPage";
import { UsersPage } from "./pages/UsersPage";
import { SettingsPage } from "./pages/SettingsPage";

// Platform Operations (separate shell)
import {
  PlatformOpsLoginPage,
  PlatformOpsLayout,
  SystemHealthPage,
  ModelConfigPage,
} from "./pages/PlatformOps";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />

          {/* Platform Operations — separate shell, own login */}
          <Route path="/platform-ops/login" element={<PlatformOpsLoginPage />} />
          <Route
            path="/platform-ops"
            element={
              <ProtectedRoute>
                <PlatformOpsLayout />
              </ProtectedRoute>
            }
          >
            <Route index element={<Navigate to="/platform-ops/system-health" replace />} />
            <Route path="system-health" element={<SystemHealthPage />} />
            <Route path="model-config" element={<ModelConfigPage />} />
          </Route>

          {/* Main app shell */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/dashboard" element={<DashboardPage />} />

            {/* Patients */}
            <Route path="/patients" element={<PatientsPage />} />
            <Route path="/patients/onboarding" element={<PatientOnboardingPage />} />

            {/* Consent */}
            <Route path="/consent" element={<ConsentQueuePage />} />
            <Route path="/consent/capture" element={<ConsentCapturePage />} />
            <Route path="/consent/success" element={<ConsentSuccessPage />} />

            {/* Records */}
            <Route path="/records" element={<RecordsPage />} />

            {/* Inbox + Compose */}
            <Route path="/inbox" element={<InboxPage />} />
            <Route path="/inbox/compose" element={<ComposePage />} />

            {/* Review Queue */}
            <Route path="/review-queue" element={<ReviewQueuePage />} />

            {/* Escalations */}
            <Route path="/escalations" element={<EscalationsPage />} />

            {/* Audit — admin only */}
            <Route
              path="/audit"
              element={
                <ProtectedRoute roles={["admin"]}>
                  <AuditPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/audit/:eventId"
              element={
                <ProtectedRoute roles={["admin"]}>
                  <AuditEventDetailPage />
                </ProtectedRoute>
              }
            />

            {/* Users — admin only */}
            <Route
              path="/users"
              element={
                <ProtectedRoute roles={["admin"]}>
                  <UsersPage />
                </ProtectedRoute>
              }
            />

            {/* Settings */}
            <Route path="/settings" element={<SettingsPage />} />
          </Route>

          {/* Catch-all */}
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
