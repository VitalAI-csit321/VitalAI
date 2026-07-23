// Reusable UI components — no colours, grayscale only

// Button
export function Button({ children, variant = "primary", size = "md", onClick, type = "button", className = "" }) {
  const base = "inline-flex items-center justify-center font-medium rounded border cursor-pointer transition-colors focus:outline-none";
  const sizes = { sm: "px-3 py-1 text-xs", md: "px-4 py-2 text-sm", lg: "px-6 py-2.5 text-sm" };
  const variants = {
    primary: "bg-gray-900 text-white border-gray-900 hover:bg-gray-700",
    secondary: "bg-white text-gray-800 border-gray-300 hover:bg-gray-50",
    ghost: "bg-transparent text-gray-600 border-transparent hover:bg-gray-100",
  };
  return (
    <button type={type} onClick={onClick} className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}>
      {children}
    </button>
  );
}

// Badge / Status pill
export function Badge({ label, variant = "default" }) {
  const variants = {
    default: "bg-gray-100 text-gray-700 border-gray-300",
    outline: "bg-white text-gray-700 border-gray-400",
    dark: "bg-gray-800 text-white border-gray-800",
    high: "bg-gray-800 text-white border-gray-800",
    medium: "bg-gray-400 text-white border-gray-400",
    low: "bg-white text-gray-600 border-gray-400",
    open: "bg-white text-gray-700 border-gray-400",
    review: "bg-gray-200 text-gray-800 border-gray-400",
    done: "bg-gray-100 text-gray-500 border-gray-300",
    urg: "bg-gray-900 text-white border-gray-900",
    new: "bg-gray-200 text-gray-800 border-gray-300",
  };
  const cls = variants[variant.toLowerCase()] || variants.default;
  return (
    <span className={`inline-block px-2 py-0.5 text-xs font-medium rounded border ${cls}`}>
      {label}
    </span>
  );
}

// Stat card for dashboard
export function StatCard({ label, value, sub }) {
  return (
    <div className="bg-white border border-gray-200 rounded p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-3xl font-bold text-gray-900 leading-none mb-1">{value}</p>
      <p className="text-xs text-gray-400">{sub}</p>
    </div>
  );
}

// Generic card wrapper
export function Card({ children, className = "" }) {
  return (
    <div className={`bg-white border border-gray-200 rounded p-4 ${className}`}>
      {children}
    </div>
  );
}

// Section title inside pages
export function PageTitle({ title, sub }) {
  return (
    <div className="mb-5">
      <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
      {sub && <p className="text-sm text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

// Table wrapper with header + rows
export function DataTable({ columns, children }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            {columns.map((col) => (
              <th key={col} className="text-left px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

// Table row
export function TableRow({ children, onClick }) {
  return (
    <tr
      onClick={onClick}
      className={`border-b border-gray-100 hover:bg-gray-50 ${onClick ? "cursor-pointer" : ""}`}
    >
      {children}
    </tr>
  );
}

// Table cell
export function TableCell({ children, className = "" }) {
  return <td className={`px-3 py-2.5 text-gray-700 ${className}`}>{children}</td>;
}

// Text input
export function Input({ label, placeholder, type = "text", id, className = "" }) {
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      {label && <label htmlFor={id} className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</label>}
      <input
        id={id}
        type={type}
        placeholder={placeholder}
        className="border border-gray-300 rounded px-3 py-2 text-sm text-gray-800 placeholder-gray-400 focus:outline-none focus:border-gray-500 bg-white"
      />
    </div>
  );
}

// Select dropdown
export function Select({ label, id, options = ["Any"], className = "" }) {
  return (
    <div className={`flex flex-col gap-1 ${className}`}>
      {label && <label htmlFor={id} className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</label>}
      <select
        id={id}
        className="border border-gray-300 rounded px-3 py-2 text-sm text-gray-700 bg-white focus:outline-none focus:border-gray-500"
      >
        {options.map((o) => <option key={o}>{o}</option>)}
      </select>
    </div>
  );
}

// Checkbox
export function Checkbox({ label, defaultChecked = false }) {
  return (
    <label className="flex items-start gap-2 text-sm text-gray-700 cursor-pointer">
      <input type="checkbox" defaultChecked={defaultChecked} className="mt-0.5 accent-gray-800" />
      <span>{label}</span>
    </label>
  );
}

// Toggle switch
export function Toggle({ active = true }) {
  return (
    <div className={`relative inline-flex w-10 h-5 rounded-full border transition-colors ${active ? "bg-gray-800 border-gray-800" : "bg-gray-200 border-gray-300"}`}>
      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${active ? "translate-x-5" : "translate-x-0.5"}`} />
    </div>
  );
}

// Priority dot indicator
export function PriorityDot({ priority }) {
  const styles = { High: "bg-gray-900", Medium: "bg-gray-400", Low: "bg-transparent border border-gray-400" };
  return (
    <span className="flex items-center gap-1.5 text-sm text-gray-600">
      <span className={`inline-block w-2.5 h-2.5 rounded-full ${styles[priority]}`} />
      {priority}
    </span>
  );
}

// Search bar used in top nav
export function SearchBar({ placeholder = "Search..." }) {
  return (
    <input
      type="search"
      placeholder={placeholder}
      className="border border-gray-300 rounded px-3 py-1.5 text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:border-gray-400 bg-white w-72"
    />
  );
}

// Step indicator for multi-step forms
export function Stepper({ steps, current }) {
  return (
    <div className="flex items-center gap-0 mb-6">
      {steps.map((step, i) => {
        const active = i === current;
        const done = i < current;
        return (
          <div key={step} className="flex items-center">
            <div className="flex items-center gap-2">
              <div className={`w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-bold ${
                done ? "bg-gray-800 border-gray-800 text-white"
                : active ? "border-gray-900 text-gray-900 bg-white"
                : "border-gray-300 text-gray-400 bg-white"
              }`}>
                {i + 1}
              </div>
              <span className={`text-sm ${active ? "font-semibold text-gray-900" : "text-gray-400"}`}>{step}</span>
            </div>
            {i < steps.length - 1 && <div className="h-px w-12 bg-gray-300 mx-2" />}
          </div>
        );
      })}
    </div>
  );
}

// Empty placeholder block (for wireframe areas not yet built)
export function Placeholder({ height = "h-48", label = "" }) {
  return (
    <div className={`${height} flex items-center justify-center border border-dashed border-gray-300 rounded text-sm text-gray-400 bg-gray-50`}>
      {label}
    </div>
  );
}
