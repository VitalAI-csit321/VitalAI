import ray
import os

from pypdf import PdfReader

@ray.remote
def load_document(file_path: str):
    """
    Loads documents from the synthetic patient dataset.

    Expected structure:

    Synthetic_Dataset/
        Patient_ID/
            Admin/
                document.txt
            Clinical/
                document.pdf

    Returns:
        {
            "patient_id": ...,
            "text": ...,
            "metadata": {...}
        }
    """
    # -----------------------------
    # Extract metadata
    # -----------------------------
    filename = os.path.basename(file_path)
    patient_id = os.path.basename(
        os.path.dirname(
            os.path.dirname(file_path)
        )
    )

    doc_folder = os.path.basename(
        os.path.dirname(file_path)
    )

    # -----------------------------
    # Determine file type
    # -----------------------------
    extension = os.path.splitext(file_path)[1].lower()

    # -----------------------------
    # Load PDF
    # -----------------------------
    if extension == ".pdf":
        reader = PdfReader(file_path)
        text = "\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )
    # -----------------------------
    # Load TXT
    # -----------------------------
    elif extension == ".txt":
        with open(
            file_path,
            "r",
            encoding="utf-8"
        ) as f:
            text = f.read()
    else:
        raise ValueError(
            f"Unsupported file type: {extension}"
        )
    # -----------------------------
    # Return document object
    # -----------------------------
    return {
        "patient_id": patient_id,
        "text": text,
        "metadata": {
            "filename": filename,
            "document_type": doc_folder,
            "file_path": file_path,
        }
    }