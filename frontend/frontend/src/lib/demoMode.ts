// Set VITE_DEMO_MODE=true in .env to preview the UI with sample data and no
// backend/login required. Never set this in a real deployment — see README.
export function isDemoMode(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "true";
}
