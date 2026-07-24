import uuid

from app.storage import object_storage


def test_put_and_get_object_roundtrip():
    key = f"test-fixtures/{uuid.uuid4()}.txt"
    object_storage.put_object(key, b"hello vitalai", "text/plain")

    result = object_storage.get_object(key)

    assert result == b"hello vitalai"


def test_get_object_returns_exact_bytes_for_binary_content():
    key = f"test-fixtures/{uuid.uuid4()}.bin"
    payload = bytes(range(256))
    object_storage.put_object(key, payload, "application/octet-stream")

    result = object_storage.get_object(key)

    assert result == payload
