import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listMessages } from "../api/misc";
import type { Message, MessagePriority } from "../api/types";
import { Avatar, Spinner } from "../components/ui";

type Tab = "all" | "urgent" | "normal" | "fyi";

function priorityBadge(p: MessagePriority) {
  if (p === "urgent")
    return <span className="rounded bg-red-500 px-1.5 py-0.5 text-[10px] font-bold text-white">URG</span>;
  return null;
}

export function InboxPage() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Message[]>([]);
  const [selected, setSelected] = useState<Message | null>(null);
  const [tab, setTab] = useState<Tab>("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listMessages()
      .then((m) => {
        setMessages(m);
        setSelected(m[0] ?? null);
      })
      .finally(() => setLoading(false));
  }, []);

  const filtered = messages.filter((m) => (tab === "all" ? true : m.priority === tab));
  const unread = messages.filter((m) => m.unread).length;
  const urgent = messages.filter((m) => m.priority === "urgent").length;

  const tabs: { key: Tab; label: string }[] = [
    { key: "all", label: `All (${messages.length})` },
    { key: "urgent", label: `Urgent (${urgent})` },
    { key: "normal", label: "Normal" },
    { key: "fyi", label: "FYI" },
  ];

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
                const active = selected?.id === m.id;
                return (
                  <button
                    key={m.id}
                    onClick={() => setSelected(m)}
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
                        {m.unread && m.priority !== "urgent" && (
                          <span className="rounded bg-brand px-1.5 py-0.5 text-[10px] font-bold text-white">
                            NEW
                          </span>
                        )}
                      </div>
                      <div className="truncate text-sm text-slate-600">{m.subject}</div>
                      <div className="mt-0.5 text-xs text-slate-400">{m.receivedLabel}</div>
                    </div>
                  </button>
                );
              })}
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
                    </div>
                    <div className="text-xs text-slate-500">To: {selected.toName}</div>
                    <div className="text-xs text-slate-400">Today at 14:22</div>
                  </div>
                </div>

                <h2 className="mt-5 text-base font-semibold text-slate-900">{selected.subject}</h2>
                <div className="my-4 h-px bg-slate-100" />
                <div className="whitespace-pre-line text-sm leading-relaxed text-slate-700">
                  {selected.body}
                </div>

                <div className="mt-6 flex gap-3">
                  <button className="rounded-lg bg-brand px-4 py-2 text-sm font-semibold text-white hover:bg-brand-hover">
                    Reply
                  </button>
                  <button className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
                    Escalate
                  </button>
                  <button className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50">
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
