import ray
import re

@ray.remote
def clean_text(doc: dict):
    text = doc["text"]

    # normalisation (safe for clinical NLP)
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    # DO NOT remove numbers (important for dosage, vitals)
    # DO NOT aggressively strip punctuation (important for medical abbreviations)

    return {
        **doc,
        "clean_text": text.strip()
    }