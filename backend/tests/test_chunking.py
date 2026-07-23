from app.rag.chunking import chunk_text


def test_chunk_text_splits_on_chunk_size():
    text = "a" * 1200
    chunks = chunk_text(text, chunk_size=500)
    assert [len(c) for c in chunks] == [500, 500, 200]
    assert "".join(chunks) == text


def test_chunk_text_shorter_than_chunk_size_returns_one_chunk():
    chunks = chunk_text("short text", chunk_size=500)
    assert chunks == ["short text"]


def test_chunk_text_default_chunk_size_is_500():
    text = "b" * 1000
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert len(chunks[0]) == 500
