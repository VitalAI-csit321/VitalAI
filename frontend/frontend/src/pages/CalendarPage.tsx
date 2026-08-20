import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { getCalendarMonth, getDayView, listAppointments } from "../api/appointments";
import { listDoctors } from "../api/doctors";
import type { Appointment, AppointmentStatus, AppointmentType, CalendarMonth, DayView, Doctor } from "../api/types";
import { useAuth } from "../lib/auth";
import { Spinner, StatusBadge } from "../components/ui";
import {
  MONTH_NAMES, STATUS_LABEL, STATUS_TONE, TYPE_COLOR, TYPE_LABEL,
  formatDateLong, formatDateShort, formatTime, patientDisplayName, toDateInputValue,
} from "../components/calendarHelpers";

type ViewMode = "month" | "week" | "day" | "list";

function StatCards({ stats }: { stats: { scheduled: number; pendingConfirmation: number; confirmedToday: number; cancellations: number } }) {
  const cards = [
    { label: "Scheduled", value: stats.scheduled, color: "border-emerald-500" },
    { label: "Pending Confirmation", value: stats.pendingConfirmation, color: "border-amber-500" },
    { label: "Confirmed Today", value: stats.confirmedToday, color: "border-emerald-500" },
    { label: "Cancellations", value: stats.cancellations, color: "border-red-500" },
  ];
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      {cards.map(c => (
        <div key={c.label} className={`rounded-xl border-l-4 ${c.color} border-y border-r border-slate-200 bg-white p-4`}>
          <div className="text-2xl font-bold text-slate-900">{c.value}</div>
          <div className="mt-0.5 text-sm text-slate-500">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function ViewSwitch({ view, onChange }: { view: ViewMode; onChange: (v: ViewMode) => void }) {
  const options: { key: ViewMode; label: string }[] = [
    { key: "month", label: "Month" }, { key: "week", label: "Week" },
    { key: "day", label: "Day" }, { key: "list", label: "List" },
  ];
  return (
    <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
      {options.map(o => (
        <button key={o.key} onClick={() => onChange(o.key)}
          className={`rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors ${view === o.key ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-50"}`}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---------------- Month view ----------------

function MonthView({ data, anchorDate, onSelectDay, selectedDay, onOpen }: {
  data: CalendarMonth; anchorDate: Date; onSelectDay: (iso: string) => void; selectedDay: string | null;
  onOpen: (id: string) => void;
}) {
  const navigate = useNavigate();
  const byDate = useMemo(() => new Map(data.days.map(d => [d.date, d])), [data]);
  const firstOfMonth = new Date(anchorDate.getFullYear(), anchorDate.getMonth(), 1);
  const startWeekday = firstOfMonth.getDay(); // 0=Sun
  const daysInMonth = new Date(anchorDate.getFullYear(), anchorDate.getMonth() + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(startWeekday).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];
  while (cells.length % 7 !== 0) cells.push(null);

  const todayIso = toDateInputValue(new Date());
  const selectedCell = selectedDay ? byDate.get(selectedDay) : undefined;

  return (
    <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => <div key={d} className="px-3 py-2 text-center">{d}</div>)}
        </div>
        <div className="grid grid-cols-7">
          {cells.map((day, i) => {
            if (day === null) return <div key={i} className="min-h-[100px] border-b border-r border-slate-100 bg-slate-50/40" />;
            const iso = toDateInputValue(new Date(anchorDate.getFullYear(), anchorDate.getMonth(), day));
            const cell = byDate.get(iso);
            const isToday = iso === todayIso;
            const isSelected = iso === selectedDay;
            const items = cell?.appointments ?? [];
            const shown = items.slice(0, 3);
            const extra = items.length - shown.length;
            return (
              <button key={i} onClick={() => onSelectDay(iso)}
                className={`min-h-[100px] border-b border-r border-slate-100 p-1.5 text-left align-top transition-colors hover:bg-slate-50 ${isSelected ? "ring-2 ring-inset ring-brand" : ""}`}>
                <span className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-sm ${isToday ? "bg-brand font-semibold text-white" : "text-slate-700"}`}>{day}</span>
                <div className="mt-1 space-y-1">
                  {shown.map(a => (
                    <div key={a.id} className={`truncate rounded px-1.5 py-0.5 text-[11px] font-medium ${a.status === "cancelled" ? "bg-slate-100 text-slate-400 line-through" : `${TYPE_COLOR[a.appointmentType].bg} ${TYPE_COLOR[a.appointmentType].text}`}`}>
                      {formatTime(a.timeSlot)} {patientDisplayName(a)}
                    </div>
                  ))}
                  {extra > 0 && <div className="px-1.5 text-[11px] text-slate-400">+{extra} more</div>}
                </div>
              </button>
            );
          })}
        </div>
        <div className="flex flex-wrap gap-4 border-t border-slate-100 px-4 py-2.5 text-xs text-slate-500">
          {(["new_patient", "follow_up", "procedure"] as AppointmentType[]).map(t => (
            <span key={t} className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-full ${TYPE_COLOR[t].dot}`} />{TYPE_LABEL[t]}</span>
          ))}
          <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-slate-400" />Cancelled</span>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        {selectedCell ? (
          <>
            <div className="text-sm font-semibold text-slate-900">{formatDateLong(selectedCell.date + "T00:00:00")}</div>
            <div className="mt-0.5 text-xs text-slate-500">{selectedCell.total} appointment{selectedCell.total === 1 ? "" : "s"}</div>
            <div className="mt-3 space-y-2">
              {selectedCell.appointments.length === 0 && <p className="text-sm text-slate-400">No appointments.</p>}
              {selectedCell.appointments.map(a => (
                <button key={a.id} onClick={() => onOpen(a.id)} className="block w-full rounded-lg border border-slate-100 p-2.5 text-left hover:border-slate-200 hover:bg-slate-50">
                  <div className="flex items-center justify-between">
                    <span className={`text-sm font-medium ${a.status === "cancelled" ? "text-slate-400 line-through" : "text-slate-900"}`}>{formatTime(a.timeSlot)}</span>
                    <StatusBadge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</StatusBadge>
                  </div>
                  <div className={`mt-0.5 text-sm ${a.status === "cancelled" ? "text-slate-400 line-through" : "text-slate-700"}`}>{patientDisplayName(a)}</div>
                  <div className="mt-0.5 text-xs text-slate-500">{TYPE_LABEL[a.appointmentType]} · {a.doctorName ?? "Unassigned"}</div>
                </button>
              ))}
            </div>
          </>
        ) : (
          <p className="text-sm text-slate-400">Select a day to see its appointments.</p>
        )}
        <button onClick={() => navigate("/calendar/new")} className="mt-4 w-full rounded-lg border border-slate-200 py-2 text-sm font-medium text-brand hover:bg-slate-50">+ Add Appointment</button>
      </div>
    </div>
  );
}

// ---------------- Week view ----------------

function WeekView({ appointments, weekStart, onOpen }: { appointments: Appointment[]; weekStart: Date; onOpen: (id: string) => void }) {
  const days = Array.from({ length: 7 }, (_, i) => { const d = new Date(weekStart); d.setDate(d.getDate() + i); return d; });
  const hours = Array.from({ length: 10 }, (_, i) => 8 + i); // 8am start marks, last row covers 5-6pm
  const HOUR_PX = 56;

  const byDay = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const d of days) map.set(toDateInputValue(d), []);
    for (const a of appointments) {
      const key = toDateInputValue(new Date(a.timeSlot));
      if (map.has(key)) map.get(key)!.push(a);
    }
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appointments, weekStart]);

  return (
    <div className="mt-4 overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <div className="min-w-[720px]">
        <div className="grid grid-cols-[56px_repeat(7,1fr)] border-b border-slate-200">
          <div />
          {days.map(d => (
            <div key={d.toISOString()} className="border-l border-slate-100 py-2 text-center">
              <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{d.toLocaleDateString("en-US", { weekday: "short" })}</div>
              <div className="text-sm font-bold text-slate-900">{d.getDate()}</div>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-[56px_repeat(7,1fr)]">
          <div>
            {hours.map(h => (
              <div key={h} className="relative border-t border-slate-100 pr-2 text-right text-[11px] text-slate-400" style={{ height: HOUR_PX }}>
                <span className="absolute -top-2 right-2">{h % 12 === 0 ? 12 : h % 12}{h < 12 ? "am" : "pm"}</span>
              </div>
            ))}
          </div>
          {days.map(d => {
            const key = toDateInputValue(d);
            const items = byDay.get(key) ?? [];
            return (
              <div key={key} className="relative border-l border-slate-100">
                {hours.map(h => (
                  <div key={h} className={`border-t border-slate-100 ${h === 12 ? "bg-[repeating-linear-gradient(45deg,transparent,transparent_6px,#f1f5f9_6px,#f1f5f9_12px)]" : ""}`} style={{ height: HOUR_PX }} />
                ))}
                {items.map(a => {
                  const start = new Date(a.timeSlot);
                  const startHour = start.getHours() + start.getMinutes() / 60;
                  if (startHour < hours[0] || startHour > hours[hours.length - 1] + 1) return null;
                  const top = (startHour - hours[0]) * HOUR_PX;
                  const height = Math.max((a.durationMinutes / 60) * HOUR_PX, 20);
                  const cancelled = a.status === "cancelled";
                  return (
                    <button key={a.id} onClick={() => onOpen(a.id)}
                      className={`absolute left-0.5 right-0.5 overflow-hidden rounded border-l-2 px-1.5 py-0.5 text-left text-[11px] ${cancelled ? "border-slate-300 bg-slate-50 text-slate-400 line-through" : `${TYPE_COLOR[a.appointmentType].border} ${TYPE_COLOR[a.appointmentType].bg} ${TYPE_COLOR[a.appointmentType].text}`}`}
                      style={{ top, height }}>
                      <div className="font-semibold">{patientDisplayName(a)}</div>
                      <div>{formatTime(a.timeSlot)}</div>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ---------------- Day view ----------------

function DayViewPanel({ data, onOpen, onNew }: { data: DayView; onOpen: (id: string) => void; onNew: () => void }) {
  const hours = Array.from({ length: 10 }, (_, i) => 8 + i);
  const HOUR_PX = 64;
  return (
    <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_280px]">
      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
        {hours.map(h => {
          const isLunch = h === 12;
          const items = data.appointments.filter(a => new Date(a.timeSlot).getHours() === h);
          return (
            <div key={h} className="flex border-b border-slate-100 last:border-0" style={{ minHeight: HOUR_PX }}>
              <div className="w-20 shrink-0 border-r border-slate-100 px-3 py-2 text-xs text-slate-400">
                {h % 12 === 0 ? 12 : h % 12}{h < 12 ? " AM" : " PM"}
              </div>
              <div className={`flex-1 p-1.5 ${isLunch ? "bg-[repeating-linear-gradient(45deg,transparent,transparent_6px,#f1f5f9_6px,#f1f5f9_12px)]" : ""}`}>
                {isLunch && items.length === 0 && <div className="flex h-full items-center justify-center text-xs italic text-slate-400">LUNCH BREAK</div>}
                {items.map(a => {
                  const cancelled = a.status === "cancelled";
                  return (
                    <button key={a.id} onClick={() => onOpen(a.id)}
                      className={`mb-1 flex w-full items-center justify-between rounded-lg border-l-4 px-3 py-2 text-left ${cancelled ? "border-slate-300 bg-slate-50" : `${TYPE_COLOR[a.appointmentType].border} ${TYPE_COLOR[a.appointmentType].bg}`}`}>
                      <div>
                        <div className={`text-sm font-semibold ${cancelled ? "text-slate-400 line-through" : "text-slate-900"}`}>{patientDisplayName(a)}</div>
                        <div className="text-xs text-slate-500">{TYPE_LABEL[a.appointmentType]} · {a.doctorName ?? "Unassigned"}{a.location ? ` · ${a.location}` : ""}</div>
                      </div>
                      <StatusBadge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</StatusBadge>
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      <div className="space-y-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="text-sm font-semibold text-slate-900">Day Overview</div>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between"><dt className="text-slate-500">{data.appointments.length} appointments</dt></div>
            {Object.entries(data.statusBreakdown).map(([status, count]) => (
              <div key={status} className="flex justify-between">
                <dt className="capitalize text-slate-500">{status}</dt><dd className="font-medium text-slate-900">{count}</dd>
              </div>
            ))}
            <div className="flex justify-between border-t border-slate-100 pt-2">
              <dt className="text-slate-500">Total booked</dt>
              <dd className="font-medium text-slate-900">{(data.totalBookedMinutes / 60).toFixed(1)}h</dd>
            </div>
          </dl>
        </div>
        {data.providers.length > 0 && (
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Providers</div>
            <div className="mt-2 space-y-2">
              {data.providers.map(p => (
                <div key={p.doctorId} className="flex items-center justify-between text-sm">
                  <span className="text-slate-700">{p.doctorName}</span>
                  <span className="font-medium text-slate-900">{p.appointmentCount}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <button onClick={onNew} className="w-full rounded-lg border border-slate-200 bg-white py-2.5 text-sm font-medium text-brand hover:bg-slate-50">+ Add new appointment</button>
      </div>
    </div>
  );
}

// ---------------- List view ----------------

function ListViewPanel({ month, onOpen, doctors }: { month: CalendarMonth | null; onOpen: (id: string) => void; doctors: Doctor[] }) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<AppointmentType | "">("");
  const [statusFilter, setStatusFilter] = useState<AppointmentStatus | "">("");
  const [providerFilter, setProviderFilter] = useState("");
  const [items, setItems] = useState<Appointment[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    const t = setTimeout(() => {
      listAppointments({
        search: search || undefined, appointmentType: typeFilter || undefined,
        status: statusFilter || undefined, doctorId: providerFilter || undefined, limit: 100,
      }).then(res => { setItems(res.items); setTotal(res.total); }).catch(() => {}).finally(() => setLoading(false));
    }, 250);
    return () => clearTimeout(t);
  }, [search, typeFilter, statusFilter, providerFilter]);

  const grouped = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    for (const a of items) {
      const key = toDateInputValue(new Date(a.timeSlot));
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(a);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  const todayIso = toDateInputValue(new Date());

  function exportCsv() {
    const rows = [
      ["Date", "Time", "Patient", "Type", "Provider", "Status"],
      ...items.map(a => [toDateInputValue(new Date(a.timeSlot)), formatTime(a.timeSlot), patientDisplayName(a), TYPE_LABEL[a.appointmentType], a.doctorName ?? "", STATUS_LABEL[a.status]]),
    ];
    const csv = rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = "appointments.csv"; link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-[1fr_280px]">
      <div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search appointments, patients, providers"
            className="w-full rounded-lg border border-slate-200 bg-white py-2.5 pl-9 pr-3 text-sm outline-none focus:border-brand" />
        </div>
        <div className="mt-2 text-xs text-slate-400">{total} result{total === 1 ? "" : "s"}</div>
        <div className="mt-3 flex flex-wrap gap-2">
          <select value={typeFilter} onChange={e => setTypeFilter(e.target.value as AppointmentType | "")} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm">
            <option value="">All Types</option>
            {(Object.keys(TYPE_LABEL) as AppointmentType[]).map(t => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select>
          <select value={providerFilter} onChange={e => setProviderFilter(e.target.value)} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm">
            <option value="">All Providers</option>
            {doctors.map(d => <option key={d.id} value={d.id}>{d.fullName}</option>)}
          </select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as AppointmentStatus | "")} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm">
            <option value="">All Statuses</option>
            {(Object.keys(STATUS_LABEL) as AppointmentStatus[]).map(s => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
          </select>
        </div>

        <div className="mt-4 space-y-4">
          {loading ? <Spinner /> : grouped.length === 0 ? (
            <p className="text-sm text-slate-400">No appointments found.</p>
          ) : grouped.map(([date, dayItems]) => (
            <div key={date}>
              <div className="mb-1.5 flex items-center gap-2 border-l-2 border-brand pl-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {formatDateLong(date + "T00:00:00")}
                {date === todayIso && <span className="rounded-full bg-brand px-2 py-0.5 text-[10px] font-bold text-white">TODAY</span>}
              </div>
              <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
                {dayItems.map((a, i) => {
                  const cancelled = a.status === "cancelled";
                  return (
                    <button key={a.id} onClick={() => onOpen(a.id)}
                      className={`flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50 ${i > 0 ? "border-t border-slate-100" : ""}`}>
                      <div className="flex min-w-0 items-center gap-3">
                        <span className={`w-16 shrink-0 text-sm font-semibold ${cancelled ? "text-slate-400" : TYPE_COLOR[a.appointmentType].text}`}>{formatTime(a.timeSlot)}</span>
                        <div className="min-w-0">
                          <div className={`truncate text-sm font-medium ${cancelled ? "text-slate-400 line-through" : "text-slate-900"}`}>{patientDisplayName(a)}</div>
                          <div className="truncate text-xs text-slate-500">{TYPE_LABEL[a.appointmentType]} · {a.durationMinutes}min · {a.doctorName ?? "Unassigned"}{a.location ? ` · ${a.location}` : ""}</div>
                        </div>
                      </div>
                      <StatusBadge tone={STATUS_TONE[a.status]}>{STATUS_LABEL[a.status]}</StatusBadge>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="space-y-4">
        {month && (
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-sm font-semibold text-slate-900">This Month</div>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex justify-between"><dt className="text-slate-500">Total appointments</dt><dd className="font-medium text-slate-900">{month.days.reduce((sum, d) => sum + d.total, 0)}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Scheduled</dt><dd className="font-medium text-emerald-600">{month.stats.scheduled}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Pending</dt><dd className="font-medium text-amber-600">{month.stats.pendingConfirmation}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-500">Cancelled</dt><dd className="font-medium text-red-500">{month.stats.cancellations}</dd></div>
            </dl>
          </div>
        )}
        <button onClick={exportCsv} className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white py-2.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
          <Download className="h-4 w-4" /> Export CSV
        </button>
      </div>
    </div>
  );
}

// ---------------- Page shell ----------------

export function CalendarPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const isDoctor = user?.role === "doctor";
  const [view, setView] = useState<ViewMode>("month");
  const [anchorDate, setAnchorDate] = useState(new Date());
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [doctors, setDoctors] = useState<Doctor[]>([]);
  const [monthData, setMonthData] = useState<CalendarMonth | null>(null);
  const [weekItems, setWeekItems] = useState<Appointment[]>([]);
  const [dayData, setDayData] = useState<DayView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!isDoctor) listDoctors().then(setDoctors).catch(() => {}); }, [isDoctor]);

  const weekStart = useMemo(() => {
    const d = new Date(anchorDate);
    const dow = (d.getDay() + 6) % 7; // Monday-based
    d.setDate(d.getDate() - dow);
    d.setHours(0, 0, 0, 0);
    return d;
  }, [anchorDate]);

  useEffect(() => {
    setLoading(true); setError(null);
    const year = anchorDate.getFullYear(); const month = anchorDate.getMonth() + 1;
    if (view === "month" || view === "list") {
      getCalendarMonth(year, month).then(setMonthData).catch(() => setError("Could not load the calendar.")).finally(() => setLoading(false));
    } else if (view === "week") {
      const weekEnd = new Date(weekStart); weekEnd.setDate(weekEnd.getDate() + 7);
      listAppointments({ dateFrom: weekStart.toISOString(), dateTo: weekEnd.toISOString(), limit: 200 })
        .then(res => setWeekItems(res.items)).catch(() => setError("Could not load the week.")).finally(() => setLoading(false));
    } else if (view === "day") {
      getDayView(toDateInputValue(anchorDate)).then(setDayData).catch(() => setError("Could not load the day.")).finally(() => setLoading(false));
    }
  }, [view, anchorDate, weekStart]);

  function step(delta: number) {
    const d = new Date(anchorDate);
    if (view === "month" || view === "list") d.setMonth(d.getMonth() + delta);
    else if (view === "week") d.setDate(d.getDate() + delta * 7);
    else d.setDate(d.getDate() + delta);
    setAnchorDate(d);
  }

  const headerLabel = view === "week"
    ? `${weekStart.toLocaleDateString("en-US", { day: "numeric", month: "short" })} - ${new Date(weekStart.getTime() + 6 * 86400000).toLocaleDateString("en-US", { day: "numeric", month: "short", year: "numeric" })}`
    : view === "day"
    ? anchorDate.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long", year: "numeric" })
    : `${MONTH_NAMES[anchorDate.getMonth()]} ${anchorDate.getFullYear()}`;

  const totalThisMonth = monthData ? monthData.days.reduce((sum, d) => sum + d.total, 0) : null;
  const stats = view === "day" ? dayData?.stats : monthData?.stats;

  return (
    <div className="p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Appointment Calendar</h1>
          {totalThisMonth !== null && (view === "month" || view === "list") && (
            <p className="mt-1 text-sm text-slate-500">{formatDateShort(anchorDate.toISOString())} · {totalThisMonth} appointments this month</p>
          )}
        </div>
        <div className="flex items-center gap-3">
          <ViewSwitch view={view} onChange={v => { setView(v); setSelectedDay(null); }} />
          <button onClick={() => navigate("/calendar/new")} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">+ New Appointment</button>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <button onClick={() => step(-1)} className="rounded-lg border border-slate-200 bg-white p-1.5 hover:bg-slate-50"><ChevronLeft className="h-4 w-4" /></button>
        <span className="text-sm font-semibold text-slate-900">{headerLabel}</span>
        <button onClick={() => step(1)} className="rounded-lg border border-slate-200 bg-white p-1.5 hover:bg-slate-50"><ChevronRight className="h-4 w-4" /></button>
      </div>

      {stats && (view === "month" || view === "day") && <div className="mt-4"><StatCards stats={stats} /></div>}

      {error && <p className="mt-4 text-sm text-red-600">{error}</p>}
      {loading && <div className="mt-8"><Spinner label={`Loading ${view} view...`} /></div>}

      {!loading && !error && view === "month" && monthData && (
        <MonthView data={monthData} anchorDate={anchorDate} selectedDay={selectedDay} onSelectDay={setSelectedDay} onOpen={id => navigate(`/calendar/${id}`)} />
      )}
      {!loading && !error && view === "week" && <WeekView appointments={weekItems} weekStart={weekStart} onOpen={id => navigate(`/calendar/${id}`)} />}
      {!loading && !error && view === "day" && dayData && (
        <DayViewPanel data={dayData} onOpen={id => navigate(`/calendar/${id}`)} onNew={() => navigate("/calendar/new")} />
      )}
      {!loading && !error && view === "list" && <ListViewPanel month={monthData} onOpen={id => navigate(`/calendar/${id}`)} doctors={doctors} />}
    </div>
  );
}
