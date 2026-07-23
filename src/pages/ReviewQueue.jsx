import { PageTitle, DataTable, TableRow, TableCell, Badge, PriorityDot, Button } from "../components/UI";
import { reviewQueue } from "../data/mockData";

const statusVariant = { OPEN: "open", REVIEW: "review", DONE: "done" };

// TODO: Replace with GET /api/review-queue
// TODO: Add pagination when data grows
export default function ReviewQueue() {
  return (
    <div>
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Administrative Review Queue</h1>
          <p className="text-sm text-gray-400 mt-0.5">18 cases · governance review</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary">Export</Button>
          <Button variant="primary">+ Add</Button>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded">
        <DataTable columns={["Case", "Submitted", "Type", "Priority", "Owner", "Reviewed", "Status"]}>
          {reviewQueue.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-mono text-xs">{row.id}</TableCell>
              <TableCell className="text-gray-400 text-xs">{row.submitted}</TableCell>
              <TableCell>{row.type}</TableCell>
              <TableCell><PriorityDot priority={row.priority} /></TableCell>
              <TableCell className="text-gray-500">[{row.owner}]</TableCell>
              <TableCell className="text-gray-400">{row.reviewed}</TableCell>
              <TableCell>
                <Badge label={row.status} variant={statusVariant[row.status] || "default"} />
              </TableCell>
            </TableRow>
          ))}
        </DataTable>
      </div>
    </div>
  );
}
