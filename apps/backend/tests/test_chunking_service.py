import pytest

from app.services.chunking_service import ParagraphChunkingService
from app.services.document_parser_service import ParsedDocument, ParsedPage


def document(*pages: ParsedPage) -> ParsedDocument:
    return ParsedDocument(
        material_id="material-1",
        course_id="course-1",
        title="lecture.txt",
        pages=pages,
        full_text="\n\n".join(page.text for page in pages),
    )


def test_long_mixed_text_uses_character_overlap() -> None:
    text = "가" * 1100 + "A" * 1100

    chunks = ParagraphChunkingService().create_chunks(
        document(ParsedPage(page_number=1, text=text))
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2]
    assert [chunk.char_count for chunk in chunks] == [1000, 1000, 500]
    assert chunks[1].chunk_text.startswith(chunks[0].chunk_text[-150:])
    assert chunks[2].chunk_text.startswith(chunks[1].chunk_text[-150:])
    assert all(chunk.page_number == 1 for chunk in chunks)
    assert all(chunk.course_id == "course-1" for chunk in chunks)
    assert all(chunk.material_id == "material-1" for chunk in chunks)


def test_paragraph_boundary_is_preferred_before_size_limit() -> None:
    first_paragraph = "A" * 600
    second_paragraph = "B" * 600

    chunks = ParagraphChunkingService().create_chunks(
        document(
            ParsedPage(
                page_number=2,
                text=f"{first_paragraph}\n\n{second_paragraph}",
            )
        )
    )

    assert chunks[0].chunk_text == first_paragraph
    assert chunks[1].chunk_text.startswith(first_paragraph[-150:])
    assert chunks[1].chunk_text.endswith(second_paragraph)
    assert all(chunk.char_count == len(chunk.chunk_text) for chunk in chunks)


def test_page_numbers_and_global_indexes_are_preserved() -> None:
    chunks = ParagraphChunkingService().create_chunks(
        document(
            ParsedPage(page_number=1, text="  첫 페이지  "),
            ParsedPage(page_number=2, text=" \n\n "),
            ParsedPage(page_number=3, text="셋째 페이지"),
        )
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert [chunk.page_number for chunk in chunks] == [1, 3]
    assert [chunk.chunk_text for chunk in chunks] == ["첫 페이지", "셋째 페이지"]
    assert [chunk.section_title for chunk in chunks] == [None, None]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"chunk_size": 0},
        {"chunk_size": 100, "chunk_overlap": 100},
        {"chunk_size": 100, "chunk_overlap": -1},
        {"chunk_size": 100, "min_chunk_size": 101},
    ],
)
def test_invalid_chunk_policy_is_rejected(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        ParagraphChunkingService(**kwargs)
