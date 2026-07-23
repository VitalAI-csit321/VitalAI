import { StatCard, PageTitle, Card, Badge, Placeholder } from "../components/UI";
import { dashboardStats, pendingReviews } from "../data/mockData";

// TODO: Replace mock data with API calls to /api/dashboard/stats and /api/dashboard/pending
export default function Dashboard() {
  return (
    <div>
      <PageTitle title="Overview" sub="Welcome back, [User Name]" />

      {/* Stat cards row */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {dashboardStats.map((stat) => (
          <StatCard key={stat.id} label={stat.label} value={stat.value} sub={stat.sub} />
        ))}
      </div>

      {/* Main content row */}
      <div className="grid grid-cols-3 gap-4">
        {/* Workflow status — takes 2 cols */}
        <Card className="col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-gray-800">Workflow Status</h2>
            <span className="text-xs text-gray-400">This week</span>
          </div>
          {/* TODO: Replace with chart component when charts library is added */}
          <Placeholder height="h-56" label="Chart — workflow status (future)" />
        </Card>

        {/* Pending reviews */}
        <Card>
          <h2 className="text-sm font-semibold text-gray-800 mb-4">Pending Reviews</h2>
          <ul className="flex flex-col gap-3">
            {pendingReviews.map((item) => (
              <li key={item.id} className="flex items-center justify-between border-b border-gray-100 pb-2 last:border-0 last:pb-0">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-gray-400 shrink-0" />
                  <div>
                    <div className="h-2.5 bg-gray-200 rounded w-36 mb-1" />
                    <div className="h-2 bg-gray-100 rounded w-24" />
                  </div>
                </div>
                <Badge label={item.tag} variant="outline" />
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
