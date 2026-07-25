import { Bell, Search } from "lucide-react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";

export function Topbar() {
  return (
    <header className="flex items-center gap-4 border-b border-slate-200 bg-white px-6 py-3">
      <div className="relative flex-1 max-w-xl">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          type="text"
          placeholder="Search..."
          className="w-full rounded-lg border border-slate-200 bg-slate-50 py-2 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-brand focus:bg-white"
        />
      </div>
      <button
        className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100"
        aria-label="Notifications"
      >
        <Bell className="h-5 w-5" strokeWidth={1.75} />
        <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-red-500" />
      </button>
    </header>
  );
}

export function Layout() {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Topbar />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
