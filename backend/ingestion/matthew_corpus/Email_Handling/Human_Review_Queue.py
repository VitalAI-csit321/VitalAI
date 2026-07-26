class HumanReviewQueue:
    def __init__(self):
        self.queue = []

    def add(
            self,
            email,
            classification
    ):

        self.queue.append({
            "email": email,
            "prediction": classification.category,
            "confidence": classification.confidence,
        })

    def get_queue(self):
        return self.queue