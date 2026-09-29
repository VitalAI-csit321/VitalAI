import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  approveDraft,
  archiveMessage,
  deleteMessage,
  escalateMessage,
  getInboxMessage,
  listMessages,
  markMessageRead,
  rejectDraft,
  sendManualReply,
} from "../api/misc";
import type { Message, MessagePriority } from "../api/types";
import { ApiError, describeApiError } from "../lib/apiClient";
import { useAuth } from "../lib/auth";
import { listTasks } from "../api/tasks";
import { Avatar, Spinner } from "../components/ui";
import { VoicemailPlayer } from "../components/VoicemailPlayer";

type Tab = "all" | "urgent" | "archived";

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
  const [searchParams] = useSearchParams();
  const { user } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [loading, setLoading] = useState(true);
  const [showReply, setShowReply] = useState(false);
  const [editedDraft, setEditedDraft] = useState("");
  const [replyText, setReplyText] = useState("");
  const [showRejectNote, setShowRejectNote] = useState(false);
  const [rejectNote, setRejectNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [urgentCalls, setUrgentCalls] = useState(0);
  const [deepLinkError, setDeepLinkError] = useState<string | null>(null);
  const deepLinkHandled = useRef(false);
  // A message opened through ?task= that is not in the viewer's own list.
  // Mark-read, Escalate, Archive and Delete check the viewer's queue, so the
  // server would refuse them: they are not offered on it.
  const [foreignId, setForeignId] = useState<string | null>(null);

  // GET /tasks, never the inbox list: every inbox load summarises each call
  // with a model call, which must not run every 30 seconds. Doctors lack
  // view_queue, so for them each check would only log a refused request.
  useEffect(() => {
    if (user?.role === "doctor") return;
    const check = () =>
      listTasks()
        .then((tasks) =>
          setUrgentCalls(
            tasks.filter((t) => t.source === "call" && t.priority === "urgent" && t.status === "pending").length,
          ),
        )
        .catch(() => {});
    check();
    const id = window.setInterval(check, 30_000);
    return () => window.clearInterval(id);
  }, [user?.role]);

  function refresh(preferId?: string | null) {
    return listMessages(tab === "archived").then((m) => {
      setMessages(m);
      const keep = preferId ?? selectedId;
      const stillThere = keep ? m.find((x) => x.id === keep) : undefined;
      setSelectedId(stillThere ? stillThere.id : (m[0]?.id ?? null));
    });
  }

  useEffect(() => {
    setLoading(true);
    refresh(null).finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const selected = messages.find((m) => m.id === selectedId) ?? null;

  useEffect(() => {
    setEditedDraft(selected?.draftText ?? "");
    setReplyText("");
    setShowRejectNote(false);
    setRejectNote("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // Deep link from a review-queue item's "Open conversation" (?task=<id>):
  // tried once, after the first list load. The message may not be in this
  // viewer's own inbox (it is held for someone else) but they can still open
  // it if they can act on an open review item linked to it -- the server
  // decides that, not the UI (GET /inbox/{task_id}).
  useEffect(() => {
    const taskId = searchParams.get("task");
    if (!taskId || deepLinkHandled.current || loading) return;
    deepLinkHandled.current = true;
    if (messages.some((m) => m.id === taskId)) {
      setSelectedId(taskId);
      return;
    }
    getInboxMessage(taskId)
      .then((m) => {
        setForeignId(m.id);
        setMessages((prev) => [m, ...prev]);
        setSelectedId(m.id);
      })
      .catch(() => setDeepLinkError("You cannot open this message."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading, messages]);

  useEffect(() => {
    if (selected?.unread && selected.id !== foreignId) {
      setMessages((prev) =>
        prev.map((m) => (m.id === selected.id ? { ...m, unread: false } : m)),
      );
      markMessageRead(selected.id).catch(() => {
        // Low-stakes UX signal only; a failed mark-read just re-shows as
        // unread on the next full refresh, no need to surface an error.
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  // Archived is a distinct server-side query (completed status), fetched
  // fresh on tab switch above; Urgent is still a client-side priority
  // filter over whichever set is currently loaded.
  const filtered = tab === "urgent" ? messages.filter((m) => m.priority === "urgent") : messages;
  const unread = messages.filter((m) => m.unread).length;
  const urgent = messages.filter((m) => m.priority === "urgent").length;
  // Server-decided, per message (review queue spec section 7): a doctor may
  // approve their own clinical drafts, an operator may not, and the UI never
  // infers this from role alone.
  const canApprove = selected?.canApprove ?? false;
  const own = selected !== null && selected.id !== foreignId;
  const canDelete = own && (user?.role === "operator" || user?.role === "admin");

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: "All" },
    { key: "urgent", label: "Urgent" },
    { key: "archived", label: "Archived" },
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

  async function handleReject() {
    if (!selected?.draftApprovalId) return;
    setBusy(true);
    setActionError(null);
    try {
      await rejectDraft(selected.draftApprovalId, rejectNote.trim());
      setShowRejectNote(false);
      setRejectNote("");
      await refresh(selected.id);
    } catch {
      setActionError("Could not reject the draft.");
    } finally {
      setBusy(false);
    }
  }

  // Write reply (D14). Updated from the response rather than a list refresh,
  // so a message opened through its review item stays on screen, now sent.
  async function handleWriteReply() {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      const sent = await sendManualReply(selected.id, replyText);
      setMessages((prev) => prev.map((m) => (m.id === sent.id ? sent : m)));
      setReplyText("");
    } catch (e) {
      setActionError(describeApiError(e, "Could not send the reply. Try again."));
      // 409: answered meanwhile, or a draft now awaits approval. Show it as it is now.
      if (e instanceof ApiError && e.status === 409) {
        const id = selected.id;
        getInboxMessage(id)
          .then((m) => setMessages((prev) => prev.map((x) => (x.id === id ? m : x))))
          .catch(() => {});
      }
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

  async function handleDelete() {
    if (!selected) return;
    setBusy(true);
    setActionError(null);
    try {
      await deleteMessage(selected.id);
      setShowReply(false);
      await refresh(null);
    } catch {
      setActionError("Could not delete this message.");
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
        <div className="flex gap-3">
          <button onClick={() => navigate("/inbox/log-call")} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50">
            Log call
          </button>
        </div>
      </div>

      {deepLinkError && (
        <div role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          {deepLinkError}
        </div>
      )}

      {urgentCalls > 0 && (
        <div role="alert" className="mt-4 flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900">
          <span>
            <span className="font-semibold">{urgentCalls} urgent call{urgentCalls === 1 ? "" : "s"}</span> waiting for a callback.
          </span>
          <button onClick={() => { setTab("urgent"); refresh(null); }} className="font-semibold underline">
            Show
          </button>
        </div>
      )}

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
                        {m.reviewItemId && (
                          <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-bold text-purple-700">
                            IN REVIEW QUEUE
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

                {selected.reviewItemId && (
                  <button
                    onClick={() => navigate(`/review-queue?item=${selected.reviewItemId}`)}
                    className="mt-3 text-xs font-semibold text-brand underline"
                  >
                    Open in Review Queue
                  </button>
                )}

                <h2 className="mt-5 text-base font-semibold text-slate-900">{selected.subject}</h2>
                <div className="my-4 h-px bg-slate-100" />
                <div className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                  {selected.body}
                </div>

                {selected.handoverContext && !selected.draftSent && (
                  <div className="mt-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    <span className="font-semibold">Note for staff: </span>
                    {selected.handoverContext}
                  </div>
                )}

                {selected.callId && selected.hasAudio && (
                  <VoicemailPlayer key={selected.callId} callId={selected.callId} />
                )}

                {showReply && selected.canWriteReply && (
                  <div className="mt-5 rounded-lg border border-brand/30 bg-emerald-50/40 p-4">
                    <label
                      htmlFor="inbox-write-reply"
                      className="block text-xs font-semibold uppercase tracking-wide text-slate-500"
                    >
                      Write reply
                    </label>
                    <textarea
                      id="inbox-write-reply"
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      disabled={busy}
                      maxLength={10000}
                      rows={6}
                      className="mt-2 w-full resize-y rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm leading-relaxed text-slate-700 outline-none focus:border-brand disabled:opacity-60"
                    />
                    <div className="mt-3">
                      <button
                        onClick={handleWriteReply}
                        disabled={busy || replyText.trim().length === 0}
                        className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
                      >
                        {busy ? "Sending…" : "Send"}
                      </button>
                    </div>
                  </div>
                )}

                {showReply && !selected.canWriteReply && (
                  <div className="mt-5 rounded-lg border border-brand/30 bg-emerald-50/40 p-4">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                      {selected.draftSent ? "Sent reply" : "AI-suggested reply"}
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
                            <>
                              <button
                                onClick={handleSend}
                                disabled={busy || editedDraft.trim().length === 0}
                                className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover disabled:opacity-50"
                              >
                                {busy ? "Sending…" : "Approve & send"}
                              </button>
                              <button
                                onClick={() => setShowRejectNote((v) => !v)}
                                disabled={busy}
                                className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                              >
                                Reject
                              </button>
                            </>
                          ) : selected.draftApprovalId ? (
                            <span className="text-sm text-slate-500">Awaiting approval by its owner.</span>
                          ) : null}
                        </div>
                        {showRejectNote && selected.draftApprovalId && canApprove && !selected.draftSent && (
                          <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3">
                            <label htmlFor="inbox-reject-note" className="block text-xs font-medium text-red-900">
                              Reason for rejecting (required)
                            </label>
                            <textarea
                              id="inbox-reject-note"
                              value={rejectNote}
                              onChange={(e) => setRejectNote(e.target.value)}
                              disabled={busy}
                              rows={2}
                              className="mt-1 w-full rounded-lg border border-red-200 px-3 py-2 text-sm"
                            />
                            <div className="mt-2 flex gap-2">
                              <button
                                onClick={handleReject}
                                disabled={busy || rejectNote.trim().length === 0}
                                className="rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-50"
                              >
                                Confirm reject
                              </button>
                              <button
                                onClick={() => { setShowRejectNote(false); setRejectNote(""); }}
                                disabled={busy}
                                className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        )}
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
                  {own && (
                    <>
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
                    </>
                  )}
                  {selected.category === "appointment_request" && (
                    <button
                      onClick={() =>
                        navigate(
                          `/calendar/new?caseId=${selected.caseId}` +
                            `&reason=${encodeURIComponent(selected.subject ?? "")}`,
                        )
                      }
                      className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
                    >
                      Book appointment
                    </button>
                  )}
                  {canDelete && (
                    <button
                      onClick={handleDelete}
                      disabled={busy}
                      className="rounded-lg border border-red-200 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50 disabled:opacity-50"
                    >
                      Delete
                    </button>
                  )}
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
