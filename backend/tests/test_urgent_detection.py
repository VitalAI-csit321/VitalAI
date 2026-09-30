"""is_urgent(): the routing gate's first override, and POST /triage's IMMEDIATE check.

Before this, the scan was seven phrases and caught 16 of 45 synthetic emergency emails
(backend/scripts/intent_classifier/RESULTS.md). A real-mail replay auto-routed "my elderly
parent has fallen and can't get up" as an appointment request.
"""

import pytest

from app.services.task_routing_gate import TaskRoutingOutcome, evaluate_task_routing_gate
from app.services.task_routing_rules import TaskCategory
from app.services.triage_service import is_urgent, matches_any


@pytest.mark.parametrize(
    "text",
    [
        "My elderly parent has fallen and can't get up for hours now",
        "Mum had a fall this morning and hit her head",
        "My son has been popping way too many of his meds",
        "I think I took an overdose of my tablets",
        "My baby is really hard to wake and floppy",
        "Her face is drooping and her speech is slurred",
        "The bleeding will not stop",
        "His throat is swelling after he ate peanuts",
        "I can’t breathe properly",  # curly apostrophe, as phones type it
        "He had a seizure at school",
        "I have been having thoughts of suicide",
        "Tight chest and sweating since lunch",
        "She collapsed in the kitchen",
        # Indirect suicidal ideation, as people write it. The black-box run's
        # "I don't want to be alive anymore... thinking about ending it tonight"
        # matched no phrase and was urgent only because the model called it a
        # complaint.
        "I don't want to be alive anymore",
        "I have been thinking about ending it tonight",
        "Honestly I just want to die",
        "Everyone would be better off without me",
        "I don't want to live like this anymore",
        "Some days I feel like there's no reason to live",
        "I want to end it all",
        "I've thought about taking my own life",
    ],
)
def test_red_flag_symptoms_are_urgent(text):
    assert is_urgent(text)


@pytest.mark.parametrize(
    "text",
    [
        "This is not urgent, just a routine billing question",
        "Non-urgent: can I update my address?",
        "It isn't an emergency, whenever suits",
        "Nothing really urgent, just checking my results",
    ],
)
def test_a_negated_urgency_word_is_not_urgent(text):
    assert not is_urgent(text)


@pytest.mark.parametrize(
    "text",
    [
        "Not urgent, but I can't breathe when I lie down",  # a symptom is never negated
        "I have no chest pain now but did an hour ago",  # a false alarm costs a human a look
        "Not urgent, sorry. Actually it is urgent, please call",  # one live mention is enough
        "URGENT: I need my referral today",
    ],
)
def test_negation_never_hides_a_real_signal(text):
    assert is_urgent(text)


@pytest.mark.parametrize(
    "text",
    [
        "Can I book an appointment with Dr Lee next Tuesday?",
        "Please renew my EpiPen script, it expires next month",
        "My phone number is 0400 000 000",
        "Is there parking near the clinic?",
        "I'm sending it again and attending it next week, and spending it wisely",
    ],
)
def test_routine_mail_is_not_urgent(text):
    assert not is_urgent(text)


def test_the_gate_sends_a_fall_to_a_human_even_at_high_confidence():
    result = evaluate_task_routing_gate(
        TaskCategory.APPOINTMENT_REQUEST,
        0.95,
        "My elderly parent has fallen and can't get up, how hard is it to book someone?",
    )
    assert result.outcome == TaskRoutingOutcome.HUMAN_REVIEW
    assert result.override_reason == "urgent_keyword"


def test_matches_any_stays_literal_for_the_guardrails():
    # The injection guardrail relies on this: a negation must not hide a pattern.
    assert matches_any("please do not ignore previous instructions", ("ignore previous",))


# Real patient questions (ChatDoctor iCliniq test set, 2026-09-30) described chest pain with
# words between the symptom and "chest", which no literal phrase matched.
@pytest.mark.parametrize(
    "text",
    [
        "I am getting pain in the middle of my chest when I put pressure on it",
        "I am having constant pain in the middle of my chest and back",
        "There is a heavy pressure in the centre of my chest",
        "My chest is hurting since this morning",
        "My chest feels really tight and heavy",
        "Sharp pains across my chest when I walk",
        "a squeezing feeling in my chest",
    ],
)
def test_chest_pain_in_other_words_is_urgent(text):
    assert is_urgent(text)


@pytest.mark.parametrize(
    "text",
    [
        # Also from the real test set: "chest" without a chest symptom.
        "From the age of 13, my chest is developing into breast and it looks weird",
        "She is more comfortable lying on my chest and tummy all the time",
        "Bumps on my ears and now all over my back, chest, neck and knees",
        "Can I get a copy of my chest x-ray report?",
    ],
)
def test_chest_without_a_chest_symptom_is_not_urgent(text):
    assert not is_urgent(text)
