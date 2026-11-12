import logging

from app.core.logging_filters import RequestPathFilter


def test_request_logger_strips_query_credentials_and_search_terms() -> None:
    path_filter = RequestPathFilter()
    for path in ("/api/voice/courses/123/stream?token=secret", "/api/student/chat-logs?keyword=private"):
        record = logging.LogRecord(
            "uvicorn", logging.INFO, __file__, 1, "%s - %s", ("127.0.0.1", path), None
        )
        assert path_filter.filter(record)
        assert record.getMessage() == f"127.0.0.1 - {path.split('?')[0]}"
