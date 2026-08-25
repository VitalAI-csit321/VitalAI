import type { ReactNode } from "react";

// Status pill matching the prototype's badge styles across pages.
type Tone = "green" | "amber" | "red" | "gray";

const TONE: Record<Tone, string> = {
  green: "bg-emerald-100 text-emerald-700",
  amber: "bg-amber-100 text-amber-700",
  red: "bg-red-100 text-red-600",
  gray: "bg-slate-100 text-slate-500",
};

export function StatusBadge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${TONE[tone]}`}
    >
      {children}
    </span>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand" />
      {label ?? "Loading…"}
    </div>
  );
}

export function Avatar({
  initials,
  color,
  size = 40,
}: {
  initials: string;
  color?: string;
  size?: number;
}) {
  return (
    <span
      className="inline-flex shrink-0 items-center justify-center rounded-full font-semibold text-white"
      style={{
        width: size,
        height: size,
        backgroundColor: color ?? "#0d9488",
        fontSize: size * 0.4,
      }}
    >
      {initials}
    </span>
  );
}
