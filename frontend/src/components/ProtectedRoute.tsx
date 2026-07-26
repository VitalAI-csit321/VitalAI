import { Navigate } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "../lib/auth";
import { Spinner } from "./ui";
import type { Role } from "../api/types";

export function ProtectedRoute({
  children,
  roles,
}: {
  children: ReactNode;
  roles?: Role[];
}) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  // Hiding a nav item isn't access control — a URL can be typed directly. Roles
  // are enforced server-side too (verified: non-admins get 403 on audit/users);
  // this just avoids showing a page that could only ever fail to load.
  if (roles && !roles.includes(user.role)) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}

// Nav items shown in the approved sidebar (Review Queue, Escalations, Audit,
// Settings) whose page designs were not part of the 10 provided. Rather than
// invent UI the sponsor didn't approve, these route here. The endpoints exist
// on the backend; the screens can be built when their designs are approved.
export function PlaceholderPage({ title }: { title: string }) {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold text-slate-900">{title}</h1>
      <p className="mt-2 max-w-lg text-sm text-slate-500">
        This screen is part of the navigation but its design has not been provided yet. It will be
        built to match once approved.
      </p>
    </div>
  );
}
