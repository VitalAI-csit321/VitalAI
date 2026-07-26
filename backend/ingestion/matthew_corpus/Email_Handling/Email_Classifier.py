class EmailClassifier:
    def __init__(self, llm):
        self.llm = llm

    def classify(self, email):
        ...