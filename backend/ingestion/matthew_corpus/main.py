import ray
import os

from Ingestion.Loader import load_document
from Ingestion.Cleaner import clean_text
from Ingestion.Chunker import chunk_text
from Ingestion.Storage import store_chunks
from Ingestion.Document_Detector import detect_document_type

from Email_Handling.Email_Classifier import EmailClassifier
from Email_Handling.Confidence_Router import ConfidenceRouter
from Email_Handling.Intent_Router import IntentRouter
from Email_Handling.Human_Review_Queue import HumanReviewQueue

ray.init(
    ignore_reinit_error=True,
    num_cpus=2,     
)

classifier = EmailClassifier()

confidence_router = ConfidenceRouter(
    threshold=0.80
)

intent_router = IntentRouter()

review_queue = HumanReviewQueue()

def process_file(file_path):
    # Stage 1: load
    raw_text_ref = load_document.remote(file_path)
    # Stage 2: clean
    clean_text_ref = clean_text.remote(raw_text_ref)

    document = ray.get(clean_text_ref)
    document = detect_document_type(document)

    if document["source_type"] == "message":
        classification = classifier.classify(document["text"])
        if not confidence_router.should_continue(classification):
            review_queue.add(
                document,
                classification
            )

            return {
                "status":"Human Review"
            }

    # Stage 3: chunk
    chunks_ref = chunk_text.remote(clean_text_ref, 50)
    # Stage 4: store
    result_ref = store_chunks.remote(os.path.basename(file_path), chunks_ref)
    return result_ref


if __name__ == "__main__":
    data_dir = "Synth_Dataset"
    files = []

    for root, dirs, filenames in os.walk(data_dir):
        for filename in filenames:
            if filename.endswith((".txt", ".pdf")):
                files.append(
                    os.path.join(root, filename)
                )

    output = []

    for file in files:
        result = process_file(file)
        output.append(
            ray.get(result)
        )

    print("\nPIPELINE OUTPUT:")
    for result in output:
        print("\n====================")
        print("FILE:", result["file"])
        print("PATIENT:", result["patient_id"])
        print("NUMBER OF CHUNKS:", result["num_chunks"])

        for chunk in result["stored_chunks"]:
            print("\n--- CHUNK ---")
            print(chunk["text"])
            print("\nEmbedding size:")
            print(len(chunk["embedding"]))
            print("\nMetadata:")
            print(chunk["metadata"])

    print("TEST COMPLETE")
