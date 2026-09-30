import { useEffect, useState } from "react";
import { getMailboxStatus, startMailboxSignIn, type MailboxStatus } from "../../api/integrations";
import { Spinner } from "../../components/ui";
import { describeApiError } from "../../lib/apiClient";
import { timeAgo } from "../../lib/time";

// Email runs whenever the installation has it enabled; the card only reports
// whether it is working and offers "Sign in with Microsoft" when it is not.
// `returned` is Microsoft's redirect outcome (?mailbox=connected|error).
export function MailboxSection({ returned }: { returned: string | null }) {
  const [mailbox, setMailbox] = useState<MailboxStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getMailboxStatus().then(setMailbox).catch(err => setError(describeApiError(err, "Could not load the mailbox status.")));
  }, []);

  async function signIn() {
    setBusy(true);
    setError(null);
    try {
      window.location.assign(await startMailboxSignIn());
    } catch (err) {
      setError(describeApiError(err, "Could not start the Microsoft sign-in."));
      setBusy(false);
    }
  }

  if (!mailbox && !error) return <Spinner label="Checking the mailbox" />;

  return (
    <div className="space-y-4">
      {returned === "connected" && (
        <p role="status" className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
          Mailbox connected.
        </p>
      )}
      {returned === "error" && (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          The Microsoft sign-in didn't finish, so nothing changed. Try again.
        </p>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}

      {mailbox && (
        <section className="rounded-xl border border-slate-200 p-5" aria-labelledby="mailbox-heading">
          <h3 id="mailbox-heading" className="text-sm font-semibold text-slate-900">Clinic mailbox</h3>

          {!mailbox.enabled ? (
            <p className="mt-2 text-sm text-slate-600">Email isn't enabled on this installation.</p>
          ) : !mailbox.needsSignin ? (
            <div className="mt-2 text-sm">
              <p className="flex items-center gap-2 font-medium text-emerald-700">
                <span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden />
                Connected as {mailbox.account}
              </p>
              <p className="mt-1 text-slate-600">
                New emails arrive automatically.{" "}
                {mailbox.lastCheckedAt ? `Last checked ${timeAgo(mailbox.lastCheckedAt)}.` : "Waiting for the first check."}
              </p>
            </div>
          ) : (
            <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
              <div className="text-sm">
                <p className="flex items-center gap-2 font-medium text-red-700">
                  <span className="h-2 w-2 rounded-full bg-red-500" aria-hidden />
                  {mailbox.account ? "Microsoft sign-in has expired" : "Not connected"}
                </p>
                <p className="mt-1 text-slate-600">
                  New emails aren't arriving. Sign in with the clinic's Microsoft account to fix this.
                </p>
              </div>
              <button onClick={signIn} disabled={busy}
                className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50">
                {busy ? "Opening Microsoft sign-in…" : mailbox.account ? "Reconnect" : "Connect mailbox"}
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
