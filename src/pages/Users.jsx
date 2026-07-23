import { PageTitle, DataTable, TableRow, TableCell, Badge, Toggle, Button } from "../components/UI";
import { users } from "../data/mockData";

// TODO: Replace with GET /api/users
// TODO: POST /api/users/invite for invite action
// TODO: PATCH /api/users/:id for toggle active state
export default function Users() {
  return (
    <div>
      <div className="flex items-start justify-between mb-5">
        <PageTitle title="User Management (RBAC)" />
        <Button variant="primary">+ Invite User</Button>
      </div>

      <div className="bg-white border border-gray-200 rounded">
        <DataTable columns={["User", "Role", "Department", "Permissions", "Last Active", "Status"]}>
          {users.map((user) => (
            <TableRow key={user.id}>
              <TableCell>
                <div className="flex items-center gap-2">
                  <div className="w-6 h-6 rounded-full bg-gray-300 shrink-0" />
                  [{user.name}]
                </div>
              </TableCell>
              <TableCell>
                <Badge label={user.role} variant="outline" />
              </TableCell>
              <TableCell>{user.department}</TableCell>
              <TableCell className="text-gray-500">{user.permissions}</TableCell>
              <TableCell className="text-gray-400 text-xs">{user.lastActive}</TableCell>
              <TableCell>
                {/* TODO: Wire onClick to PATCH /api/users/:id/toggle */}
                <Toggle active={user.active} />
              </TableCell>
            </TableRow>
          ))}
        </DataTable>
      </div>
    </div>
  );
}
