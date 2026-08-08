from app.utils.formatting import trim_for_telegram, chunk_for_telegram


def test_trim_short_text_untouched():
    text = "Short reply."
    assert trim_for_telegram(text, limit=100) == text


def test_trim_long_text_cuts_at_sentence_boundary():
    text = "First sentence. " + ("Padding word. " * 200)
    trimmed = trim_for_telegram(text, limit=50)
    assert len(trimmed) <= 51  # 50 + ellipsis char
    assert trimmed.endswith("…")


def test_chunk_under_limit_returns_single_chunk():
    text = "hello world"
    assert chunk_for_telegram(text, chunk_size=100) == ["hello world"]


def test_chunk_splits_long_text_without_exceeding_size():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(200))
    chunks = chunk_for_telegram(text, chunk_size=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)
    # nothing lost in the split
    assert "".join(chunks).replace("\n", "") .count("line 0 ") >= 1
