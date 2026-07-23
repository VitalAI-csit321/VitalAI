import { createBrowserRouter } from "react-router-dom";
import AppLayout from "../layouts/AppLayout";
import Login from "../pages/Login";
import Dashboard from "../pages/Dashboard";
import Patients from "../pages/Patients";
import Consent from "../pages/Consent";
import Records from "../pages/Records";
import ReviewQueue from "../pages/ReviewQueue";
import Escalations from "../pages/Escalations";
import Inbox from "../pages/Inbox";
import Audit from "../pages/Audit";
import Users from "../pages/Users";
import Settings from "../pages/Settings";

const router = createBrowserRouter([
  // Public route — no layout
  { path: "/", element: <Login /> },
  { path: "/login", element: <Login /> },

  // Protected routes — all share the AppLayout
  // TODO: Add auth guard wrapper around AppLayout when auth is implemented
  {
    element: <AppLayout />,
    children: [
      { path: "/dashboard", element: <Dashboard /> },
      { path: "/patients", element: <Patients /> },
      { path: "/consent", element: <Consent /> },
      { path: "/records", element: <Records /> },
      { path: "/review-queue", element: <ReviewQueue /> },
      { path: "/escalations", element: <Escalations /> },
      { path: "/inbox", element: <Inbox /> },
      { path: "/audit", element: <Audit /> },
      { path: "/users", element: <Users /> },
      { path: "/settings", element: <Settings /> },
    ],
  },
]);

export default router;
