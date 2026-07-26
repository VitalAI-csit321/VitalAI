from dataclasses import dataclass


@dataclass
class ClassificationResult:
    category: str
    confidence: float
