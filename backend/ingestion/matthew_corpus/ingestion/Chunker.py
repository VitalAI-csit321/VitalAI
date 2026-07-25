import ray


@ray.remote
def chunk_text(document, chunk_size):
    text = document["text"]
    chunks = [
        text[i:i + chunk_size]
        for i in range(0, len(text), chunk_size)
    ]

    return {
        "patient_id": document["patient_id"],
        "metadata": document["metadata"],
        "chunks": chunks
    }