from skku_ai_rag.ingest import split_text_by_words


def test_split_text_by_words_keeps_overlap() -> None:
    text = " ".join(str(index) for index in range(12))

    chunks = split_text_by_words(text, chunk_size=5, overlap=2)

    assert chunks == [
        "0 1 2 3 4",
        "3 4 5 6 7",
        "6 7 8 9 10",
        "9 10 11",
    ]
