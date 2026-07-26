class IntentRouter:

    def route(self, classification):
        routes = {
            "appointment_booking":"calendar_agent",
            "appointment_cancellation":"calendar_agent",
            "appointment_reschedule":"calendar_agent",
            "repeat_prescription":"prescription_agent",
            "billing":"billing_agent",
            "insurance":"billing_agent",
            "medical_question":"clinical_agent",
            "referral":"clinical_agent",
            "administrative":"admin_agent",
            "spam":"discard",
            "unknown":"human_review"
        }

        return routes.get(
            classification.category,
            "human_review"
        )