export function formatDate(dateStr) {
  return new Date(dateStr).toLocaleDateString("en-AU", { day: "2-digit", month: "short", year: "numeric" });
}
export function truncate(str, n = 60) { return str.length > n ? str.slice(0, n) + "..." : str; }
export function capitalize(str) { return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase(); }
