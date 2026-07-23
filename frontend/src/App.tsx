import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./lib/auth";
import { Layout } from "./components/Layout";
import { ProtectedRoute, PlaceholderPage } from "./components/ProtectedRoute";
import { LoginPage } from "./pages/LoginPage";
import { ForgotPasswordPage } from "./pages/ForgotPasswordPage";
import { DashboardPage } from "./pages/DashboardPage";
import { PatientsPage } from "./pages/PatientsPage";
import { PatientOnboardingPage } from "./pages/PatientOnboardingPage";
import { ConsentQueuePage } from "./pages/ConsentQueuePage";
import { ConsentCapturePage } from "./pages/ConsentCapturePage";
import { ConsentSuccessPage } from "./pages/ConsentSuccessPage";
import { RecordsPage } from "./pages/RecordsPage";
import { InboxPage } from "./pages/InboxPage";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public auth routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />

          {/* Authenticated app shell */}
          <Route
            element={
              <ProtectedRoute>
                <Layout />
              </ProtectedRoute>
            }
          >
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/patients" element={<PatientsPage />} />
            <Route path="/patients/onboarding" element={<PatientOnboardingPage />} />
            <Route path="/consent" element={<ConsentQueuePage />} />
            <Route path="/consent/capture" element={<ConsentCapturePage />} />
            <Route path="/consent/success" element={<ConsentSuccessPage />} />
            <Route path="/records" element={<RecordsPage />} />
            <Route path="/inbox" element={<InboxPage />} />

            {/* Sidebar items whose designs weren't in the approved set */}
            <Route path="/review-queue" element={<PlaceholderPage title="Review Queue" />} />
            <Route path="/escalations" element={<PlaceholderPage title="Escalations" />} />
            <Route path="/audit" element={<PlaceholderPage title="Audit" />} />
            <Route path="/users" element={<PlaceholderPage title="Users" />} />
            <Route path="/settings" element={<PlaceholderPage title="Settings" />} />
          </Route>

          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
