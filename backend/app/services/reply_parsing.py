"""What the sender wrote in this message, without the history quoted under it.

A reply to the clinic arrives with our own earlier message stacked underneath,
and that message is full of dates and times we offered. Anything that reads a
reply for "which day" must not read ours. Graph's uniqueBody already does this
for Outlook mail (outlook_client); this is the fallback for everything else.

Markers are matched anywhere, not only at a line start, because
outlook_client.strip_html collapses a body onto one line.
"""

import re

# ponytail: the common English quote headers only (Gmail, Apple Mail, Outlook,
# forwarded chains). A client that quotes some other way keeps its history,
# and the extraction prompt still labels our last message as ours; add the
# marker here when a real one turns up.
_MARKERS = re.compile(
    r"On\s[^\n]{1,200}?\bwrote:"
    r"|-{2,}\s*Original Message\s*-{2,}"
    r"|-{2,}\s*Forwarded message\s*-{2,}"
    r"|Begin forwarded message:"
    r"|\bFrom:\s[^\n]{1,200}?\s(?:Sent|Date):\s"
    r"|_{10,}",
    re.IGNORECASE,
)


def strip_quoted(text: str | None) -> str:
    """The new part of a reply. Top-posted: everything above the first quote
    header. Inline (answers between "> " lines): the text above it plus every
    unquoted line below it."""
    if not text:
        return ""
    match = _MARKERS.search(text)
    head, tail = (text[: match.start()], text[match.end() :]) if match else (text, "")
    tail_lines = tail.splitlines()[1:]
    if any(line.lstrip().startswith(">") for line in tail_lines):
        head += "\n" + "\n".join(
            line for line in tail_lines if line.strip() and not line.lstrip().startswith(">")
        )
    kept = [line for line in head.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(kept).strip()
