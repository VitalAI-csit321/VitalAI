from dataclasses import dataclass


@dataclass
class Email:

    sender: str
    recipient: str
    subject: str
    body: str

    received_date: str | None = None
    patient_id: str | None = None