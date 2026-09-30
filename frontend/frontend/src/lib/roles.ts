export function roleLabel(role: string): string {
  const map: Record<string, string> = { front_desk: "Front desk", operator: "Operator", admin: "Admin", doctor: "Doctor" };
  return map[role] ?? role;
}

// A permission the user holds by role or by an admin's grant. Admin is checked by
// role because the server gives admins every permission these screens gate on.
export function hasPermission(user: { role: string; grantedPermissions: string[] } | null, permission: string): boolean {
  return !!user && (user.role === "admin" || user.grantedPermissions.includes(permission));
}
