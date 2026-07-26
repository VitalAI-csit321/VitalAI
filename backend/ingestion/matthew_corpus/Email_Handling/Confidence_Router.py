class ConfidenceRouter:

    def __init__(self, threshold=0.80):
        self.threshold = threshold

    def should_continue(self,classification):
        return (
            classification.confidence >= self.threshold
        )