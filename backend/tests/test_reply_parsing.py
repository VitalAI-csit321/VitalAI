"""reply_parsing.strip_quoted: the patient's new words, never our quoted offer.

Every fixture quotes a clinic message offering "Tuesday 29 September at
9:00am". A parser that let that through would hand the extraction step our own
date as if the patient had chosen it.
"""

import pytest

from app.services.reply_parsing import strip_quoted

OFFER = "Tuesday 29 September at 9:00am"

GMAIL_TOP_POSTED = f"""Thursday afternoon would suit me better please.

Thanks,
Jane

On Tue, 22 Sep 2026 at 10:04, VitalAI Clinic <clinic@example.com> wrote:
> Hi Jane,
>
> These times are available on Tuesday 29 September:
> - {OFFER} with Dr Rahman
"""

OUTLOOK_PLAIN = f"""Yes please, the 9am one.

Jane Citizen

From: VitalAI Clinic <clinic@example.com>
Sent: Tuesday, 22 September 2026 10:04 AM
To: Jane Citizen <jane@example.com>
Subject: RE: Appointment

Hi Jane,
These times are available on Tuesday 29 September:
- {OFFER} with Dr Rahman
"""

# What outlook_client.strip_html leaves of an HTML reply: one line.
OUTLOOK_HTML_COLLAPSED = (
    "Friday arvo if you have anything. Jane "
    "________________________________ From: VitalAI Clinic <clinic@example.com> "
    f"Sent: Tuesday, 22 September 2026 10:04 AM To: Jane Subject: RE: Appointment "
    f"Hi Jane, These times are available: - {OFFER} with Dr Rahman"
)

INLINE = f"""On Tue, 22 Sep 2026 at 10:04, VitalAI Clinic <clinic@example.com> wrote:
> Please reply with your date of birth
15/10/1989
> and a phone number
0412 345 678
> These times are available: {OFFER}
Can I do the Wednesday instead?
"""

FORWARDED = f"""Booking this for my mum, see below.

---------- Forwarded message ---------
From: VitalAI Clinic <clinic@example.com>
Date: Tue, 22 Sep 2026 at 10:04
Subject: Appointment
- {OFFER} with Dr Rahman
"""

APPLE_FORWARD = f"""Can you move it to Thursday?

Begin forwarded message:

From: VitalAI Clinic <clinic@example.com>
{OFFER}
"""

OUTLOOK_ORIGINAL_MESSAGE = f"""Monday is better.

-----Original Message-----
From: VitalAI Clinic
{OFFER}
"""


@pytest.mark.parametrize(
    ("body", "kept"),
    [
        (GMAIL_TOP_POSTED, "Thursday afternoon would suit me better"),
        (OUTLOOK_PLAIN, "Yes please, the 9am one."),
        (OUTLOOK_HTML_COLLAPSED, "Friday arvo if you have anything."),
        (FORWARDED, "Booking this for my mum"),
        (APPLE_FORWARD, "Can you move it to Thursday?"),
        (OUTLOOK_ORIGINAL_MESSAGE, "Monday is better."),
    ],
    ids=["gmail", "outlook", "outlook-html", "forwarded", "apple-forward", "original-message"],
)
def test_top_posted_and_forwarded_replies_keep_only_the_new_text(body, kept):
    new = strip_quoted(body)

    assert kept in new
    assert OFFER not in new
    assert "29 September" not in new


def test_an_inline_reply_keeps_the_answers_between_the_quoted_lines():
    new = strip_quoted(INLINE)

    assert "15/10/1989" in new
    assert "0412 345 678" in new
    assert "Can I do the Wednesday instead?" in new
    assert OFFER not in new
    assert "wrote:" not in new


def test_a_message_with_no_quote_is_returned_whole():
    body = "Hi, can I get an appointment next week?\n\nThanks, Jane"
    assert strip_quoted(body) == body


def test_nothing_in_nothing_out():
    assert strip_quoted(None) == ""
    assert strip_quoted("") == ""
