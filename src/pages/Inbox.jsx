import { useState } from "react";
import { PageTitle, Badge, Button } from "../components/UI";
import { messages } from "../data/mockData";

const FILTERS = ["ALL", "URGENT", "NORMAL", "FYI"];

// TODO: Replace with GET /api/inbox and WebSocket for real-time updates
// TODO: POST /api/inbox/:id/reply for reply action
export default function Inbox() {
  const [active, setActive] = useState("ALL");
  const [selected, setSelected] = useState(messages[0]);

  const filtered = active === "ALL" ? messages
    : active === "URGENT" ? messages.filter((m) => m.tag === "URG")
    : active === "NORMAL" ? messages.filter((m) => !m.tag)
    : messages.filter((m) => m.tag === "FYI");

  return (
    <div>
      <PageTitle title="Messages & Email" />

      <div className="grid grid-cols-5 gap-4">
        {/* Inbox list */}
        <div className="col-span-2 bg-white border border-gray-200 rounded">
          {/* Filter tabs */}
          <div className="flex items-center gap-1.5 p-3 border-b border-gray-200">
            {FILTERS.map((f) => (
              <button
                key={f}
                onClick={() => setActive(f)}
                className={`px-3 py-1 rounded-full border text-xs font-medium transition-colors ${
                  active === f ? "bg-gray-900 text-white border-gray-900" : "text-gray-600 border-gray-300 hover:bg-gray-50"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          {/* Message list */}
          <ul>
            {filtered.map((msg) => (
              <li
                key={msg.id}
                onClick={() => setSelected(msg)}
                className={`flex items-start gap-3 px-4 py-3 border-b border-gray-100 cursor-pointer hover:bg-gray-50 ${
                  selected?.id === msg.id ? "bg-gray-50" : ""
                }`}
              >
                <div className="w-8 h-8 rounded-full bg-gray-300 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{msg.sender}</p>
                  <div className="h-2 bg-gray-200 rounded w-full mt-1.5" />
                  <div className="h-2 bg-gray-100 rounded w-3/5 mt-1" />
                </div>
                <div className="flex flex-col items-end gap-1 shrink-0">
                  <span className="text-xs text-gray-400">{msg.time}</span>
                  {msg.tag && <Badge label={msg.tag} variant={msg.tag === "URG" ? "dark" : "outline"} />}
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Message preview */}
        <div className="col-span-3 bg-white border border-gray-200 rounded flex flex-col">
          {selected ? (
            <>
              <div className="p-4 border-b border-gray-200 flex-1">
                <h3 className="text-base font-semibold text-gray-900 mb-1">[Subject Line of Message]</h3>
                <p className="text-xs text-gray-400 mb-4">
                  From: [{selected.sender}] · To: [User] · 14:32
                </p>
                {/* Placeholder body lines */}
                <div className="flex flex-col gap-2">
                  <div className="h-2.5 bg-gray-200 rounded w-full" />
                  <div className="h-2.5 bg-gray-200 rounded w-5/6" />
                  <div className="h-2.5 bg-gray-200 rounded w-4/5" />
                  <div className="h-2.5 bg-gray-200 rounded w-full" />
                  <div className="h-2.5 bg-gray-200 rounded w-3/5" />
                </div>
              </div>

              {/* Action bar — TODO: wire up reply/escalate/archive */}
              <div className="flex gap-2 p-4 border-t border-gray-200">
                <Button variant="primary">Reply</Button>
                <Button variant="secondary">Escalate</Button>
                <Button variant="secondary">Archive</Button>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-sm text-gray-400">
              Select a message to preview
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
