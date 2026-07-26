import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { approveDraft, archiveMessage, escalateMessage, listMessages } from "../api/misc";
import type { Message, MessagePriority } from "../api/types";
import { useAuth } from "../lib/auth";
import { Avatar, Spinner } from "../components/ui";

type Tab = "all" | "urgent" | "normal" | "fyi";

function priorityBadge(p: MessagePriority) {
  if (p === "urgent")
    return <span className="rounded bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">URG</span>;
  return null;
}

function formatCategory(category: string): string {
  return category
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function categoryBadge(category: string) {
  return (
    <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">
      {formatCategory(category)}
    </span>
  );
}

export function InboxPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [loading, setLoading] = useState(true);
  const [showReply, setShowReply] = useState(false);
  const [editedDraft, setEditedDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  function refresh(preferId?: string | null) {
    return listMessages().then((m) => {
      setMessages(m);
      const keep = preferId ?? selectedId;
      const stillThere = keep ? m.find((x) => x.id === keep) : undefined;
      setSelectedId(stillThere ? stillThere.id : (m[0]?.id ?? null));
    });
  }

  useEffect(() => {
    refresh().finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selected = messages.find((m) => m.id === selectedId) ?? null;

  useEffect(() => {
    setEditedDraft(selected?.draftText ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);
  const filtered = messages.filter((m) => (tab === "all" ? true : m.priority === tab));
  const unread = messages.filter((m) => m.unread).length;
  const urgent = messages.filter((m) => m.priority === "urgent").length;
  const canApprove = user?.role === "operator" || user?.role === "admin";

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: `All (${messages.length})` },
    { key: "urgent", label: `Urgent (${urgent})` },
    { key: "normal", label: "Normal" },
    { key: "fyi", label: "FYI" },
  ];

  async function handleSend() {
    if (!selected?.draftApprovalId || !selected.emailId) return;
    setBusy(true);
    setActionError(null);
    try {
      const edited = editedDraft.trim() !== (selected.draftText ?? "").trim();
      await approveDraft(
        selected.draftApprovalId,
        edited
          ? { draft: editedDraft, emailId: selected.emailId, taskId: selected.id }
          : undefined,
      );
      await refresh(selected.id);
    } catch {
      setActionError("Could not send the reply. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function handleEscalate() {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      await escalateMessage(selected.id);
      await refresh(selected.id);
    } catch {
      setActionError("Could not escalate this message.");
    } finally {
      setBusy(false);
    }
  }

  async function handleArchive() {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      await archiveMessage(selected.id);
      setShowReply(false);
      await refresh(null);
    } catch {
      setActionError("Could not archive this message.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Messages and email</h1>
          <p className="mt-1 text-sm text-slate-500">
            {messages.length} conversations • {unread} unread • {urgent} urgent
          </p>
        </div>
        <button onClick={() => navigate("/inbox/compose")} className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
          Compose
        </button>
      </div>

      {loading ? (
        <div className="mt-8">
          <Spinner />
        </div>
      ) : (
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_1.4fr]">
          {/* List */}
          <div className="rounded-xl border border-slate-200 bg-white">
            <div className="flex gap-4 border-b border-slate-200 px-4 pt-3 text-sm">
              {tabs.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setTab(t.key)}
                  className={`pb-2.5 font-medium ${
                    tab === t.key
                      ? "border-b-2 border-brand text-slate-900"
                      : "text-slate-500 hover:text-slate-700"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            <div>
              {filtered.map((m) => {
                const active = selectedId === m.id;
                return (
                  <button
                    key={m.id}
                    onClick={() => {
                      setSelectedId(m.id);
                      setShowReply(false);
                      setActionError(null);
                    }}
                    className={`flex w-full items-start gap-3 border-b border-slate-100 px-4 py-3 text-left last:border-0 ${
                      active ? "bg-emerald-50/50" : "hover:bg-slate-50"
                    }`}
                  >
                    <Avatar initials={m.fromInitials} color={m.avatarColor} size={36} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span
                          className={`truncate text-sm ${m.unread ? "font-bold text-slate-900" : "font-medium text-slate-700"}`}
                        >
                          {m.fromName}
                        </span>
                        {priorityBadge(m.priority)}
                        {m.taskStatus === "escalated" && (
                          <span className="rounded bg-orange-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
                            ESCALATED
                          </span>
                        )}
                        {m.unread && m.priority !== "urgent" && m.taskStatus !== "escalated" && (
                          <span className="rounded bg-brand px-1.5 py-0.5 text-[10px] font-bold text-white">
                            NEW
                          </span>
                        )}
                      </div>
                      <div className="truncate text-sm text-slate-600">{m.subject}</div>
                      <div className="mt-1 flex items-center gap-2">
                        {categoryBadge(m.category)}
                        <span className="text-xs text-slate-400">{m.receivedLabel}</span>
                      </div>
                    </div>
                  </button>
                );
              })}
              {filtered.length === 0 && (
                <p className="px-4 py-6 text-center text-sm text-slate-400">Nothing here.</p>
              )}
            </div>
          </div>

          {/* Reading pane */}
          <div className="rounded-xl border border-slate-200 bg-white p-6">
            {selected ? (
              <>
                <div className="flex items-start gap-3">
                  <Avatar initials={selected.fromInitials} color={selected.avatarColor} size={40} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-slate-900">{selected.fromName}</span>
                      {priorityBadge(selected.priority)}
                      {categoryBadge(selected.category)}
                    </div>
                    <div className="text-xs text-slate-500">To: {selected.toName}</div>
                    <div className="text-xs text-slate-400">{selected.receivedLabel}</div>
                  </div>
                </div>

                <h2 className="mt-5 text-base font-semibold text-slate-900">{selected.subject}</h2>
                <div className="my-4 h-px bg-slate-100" />
                <div className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                  {selected.body}
                </div>

                {showReply && (
                  <div className="mt-5 rounded-lg border border-brand/30 bg-emerald-50/40 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      AI-suggested reply
                    </p>
                    {selected.draftText ? (
                      <>
                        {selected.draftSent ? (
                          <p className="mt-2 whitespace-pre-line text-sm text-slate-700">
                            {selected.draftText}
                          </p>
                        ) : (
                          <textarea
                            value={editedDraft}
                            onChange={(e) => setEditedDraft(e.target.value)}
                            disabled={busy}
                            className="mt-2 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-relaxed text-slate-700 outline-none focus:border-brand disabled:opacity-60"
                            rows={6}
                          />
                        )}
                        <div className="mt-3 flex items-center gap-3">
                          {selected.draftSent ? (
                            <span className="text-sm font-medium text-emerald-700">Already sent ✓</span>
                          ) : selected.draftApprovalId && canApprove ? (
                            <button
                              onClick={handleSend}
                              disabled={busy || editedDraft.trim().length === 0}
                              className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
                            >
                              {busy ? "Sending…" : "Approve & send"}
                            </button>
                          ) : selected.draftApprovalId ? (
                            <span className="text-sm text-slate-500">Awaiting approval from an operator.</span>
                          ) : null}
                        </div>
                      </>
                    ) : (
                      <p className="mt-2 text-sm text-slate-500">
                        No AI draft available for this message; it needs a manual reply outside this system
                        (either it went straight to human review, or the draft was blocked by the content
                        guardrail).
                      </p>
                    )}
                  </div>
                )}

                {actionError && (
                  <p className="mt-4 text-sm font-medium text-red-600">{actionError}</p>
                )}

                <div className="mt-6 flex gap-3">
                  <button
                    onClick={() => setShowReply((v) => !v)}
                    className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover"
                  >
                    Reply
                  </button>
                  <button
                    onClick={handleEscalate}
                    disabled={busy || selected.taskStatus === "escalated"}
                    className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {selected.taskStatus === "escalated" ? "Escalated" : "Escalate"}
                  </button>
                  <button
                    onClick={handleArchive}
                    disabled={busy}
                    className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                  >
                    Archive
                  </button>
                </div>

                <div className="mt-6 border-t border-slate-100 pt-4 text-xs text-slate-400">
                  Thread reference: {selected.threadReference}
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-500">Select a message to read it.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
