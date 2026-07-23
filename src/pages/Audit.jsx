import { PageTitle, DataTable, TableRow, TableCell, Badge, Button, PriorityDot } from "../components/UI";
import { auditLogs } from "../data/mockData";

const riskVariant = { High: "high", Med: "medium", Low: "low" };

// TODO: Replace with GET /api/audit-logs with query params for filtering
// TODO: Export CSV via GET /api/audit-logs/export
export default function Audit() {
  return (
    <div>
      <PageTitle title="Audit Logs & Activity" />

      {/* Filter bar */}
      <div className="flex items-center gap-2 mb-4">
        <input
          type="search"
          placeholder="Filter logs..."
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
        />
        <Button variant="secondary">User</Button>
        <Button variant="secondary">Action</Button>
        <Button variant="secondary">Date</Button>
        <Button variant="secondary">Risk</Button>
        <Button variant="primary">Export CSV</Button>
      </div>

      <div className="bg-white border border-gray-200 rounded">
        <DataTable columns={["Time", "User", "Action", "Resource", "Risk", "Status"]}>
          {auditLogs.map((log, i) => (
            <TableRow key={i}>
              <TableCell className="font-mono text-xs text-gray-500">{log.time}</TableCell>
              <TableCell className="text-gray-500">[{log.user}]</TableCell>
              <TableCell>{log.action}</TableCell>
              <TableCell className="font-mono text-xs">{log.resource}</TableCell>
              <TableCell>
                <PriorityDot priority={log.risk === "Med" ? "Medium" : log.risk} />
              </TableCell>
              <TableCell>
                <Badge label={log.status} variant="outline" />
              </TableCell>
            </TableRow>
          ))}
        </DataTable>
      </div>
    </div>
  );
}
