import { useEffect, useState } from "react";
import { fetchCallAudio } from "../api/calls";
import { ApiError } from "../lib/apiClient";

export function VoicemailPlayer({ callId }: { callId: string }) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => { if (src) URL.revokeObjectURL(src); }, [src]);

  async function load() {
    setError(null);
    try {
      setSrc(URL.createObjectURL(await fetchCallAudio(callId)));
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 410
          ? "This recording is no longer kept (30-day limit)."
          : "Could not load the recording.",
      );
    }
  }

  if (src) return <audio controls autoPlay src={src} className="mt-4 w-full" />;
  return (
    <div className="mt-4">
      <button onClick={load} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
        Play voicemail
      </button>
      {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
    </div>
  );
}
