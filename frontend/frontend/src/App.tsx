import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { Layout } from "./components/Layout";
import { ProtectedRoute } from "./components/ProtectedRoute";

// Auth
import { LoginPage } from "./pages/LoginPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { ResetPasswordPage } from "./pages/ResetPasswordPage";
import { PatientRegistrationPage } from "./pages/PatientRegistrationPage";

// Core pages (first 10 designs)
import { DashboardPage } from "./pages/DashboardPage";
import { PatientsPage } from "./pages/PatientsPage";
import { PatientOnboardingPage } from "./pages/PatientOnboardingPage";
import { PatientDetailPage } from "./pages/PatientDetailPage";
import { PatientEditPage } from "./pages/PatientEditPage";
import { CasePage } from "./pages/CasePage";
import { ContactPage } from "./pages/ContactPage";
import { ConsentQueuePage } from "./pages/ConsentQueuePage";
import { ConsentNewPage } from "./pages/ConsentNewPage";
import { ConsentCapturePage } from "./pages/ConsentCapturePage";
import { ConsentViewPage } from "./pages/ConsentViewPage";
import { ConsentSuccessPage } from "./pages/ConsentSuccessPage";
import { RecordsPage } from "./pages/RecordsPage";
import { InboxPage } from "./pages/InboxPage";

// New pages (15 new designs)
import { ReviewQueuePage } from "./pages/ReviewQueuePage";
import { AddCasePage } from "./pages/AddCasePage";
import { EscalationsPage } from "./pages/EscalationsPage";
import { AuditPage } from "./pages/AuditPage";
import { AuditEventDetailPage } from "./pages/AuditEventDetailPage";
import { UsersPage } from "./pages/UsersPage";
import { SettingsPage } from "./pages/SettingsPage";
import { CalendarPage } from "./pages/CalendarPage";
import { AppointmentDetailPage } from "./pages/AppointmentDetailPage";
import { AppointmentEditPage } from "./pages/AppointmentEditPage";
import { AppointmentNewPage } from "./pages/AppointmentNewPage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/register/:token" element={<PatientRegistrationPage />} />

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
            <Route path="/patients/:id" element={<PatientDetailPage />} />
            <Route path="/patients/:id/edit" element={<PatientEditPage />} />
            <Route path="/cases/:id" element={<CasePage />} />
            <Route path="/contacts/:id" element={<ContactPage />} />

            {/* Consent */}
            <Route path="/consent" element={<ConsentQueuePage />} />
            <Route path="/consent/new" element={<ConsentNewPage />} />
            <Route path="/consent/capture" element={<ConsentCapturePage />} />
            <Route path="/consent/:caseId/view" element={<ConsentViewPage />} />
            <Route path="/consent/success" element={<ConsentSuccessPage />} />

            {/* Records */}
            <Route path="/records" element={<RecordsPage />} />

            {/* Inbox */}
            <Route path="/inbox" element={<InboxPage />} />

            {/* Review Queue */}
            <Route path="/review-queue" element={<ReviewQueuePage />} />
            <Route path="/review-queue/add" element={<AddCasePage />} />

            {/* Escalations */}
            <Route
              path="/escalations"
              element={
                <ProtectedRoute roles={["front_desk", "operator", "admin"]}>
                  <EscalationsPage />
                </ProtectedRoute>
              }
            />

            {/* Audit: read_audit, so admins and operators an admin has granted it */}
            <Route
              path="/audit"
              element={
                <ProtectedRoute permission="read_audit">
                  <AuditPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/audit/:eventId"
              element={
                <ProtectedRoute permission="read_audit">
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

            {/* Calendar */}
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/calendar/new" element={<AppointmentNewPage />} />
            <Route path="/calendar/:id" element={<AppointmentDetailPage />} />
            <Route path="/calendar/:id/edit" element={<AppointmentEditPage />} />
          </Route>

          {/* Catch-all */}
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
