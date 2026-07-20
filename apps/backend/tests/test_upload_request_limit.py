from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_default_request_limit_reserves_multipart_overhead() -> None:
    settings = get_settings()

    assert settings.max_upload_request_size_bytes - settings.max_upload_size_bytes >= 1024 * 1024


def create_limited_client(monkeypatch, request_limit: int = 128) -> TestClient:
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "4")
    monkeypatch.setenv("MAX_UPLOAD_REQUEST_SIZE_BYTES", str(request_limit))
    get_settings.cache_clear()
    return TestClient(create_app(), raise_server_exceptions=False)


def test_material_upload_rejects_oversized_content_length_with_413(monkeypatch) -> None:
    with create_limited_client(monkeypatch) as client:
        response = client.post(
            "/api/courses/course-1/materials",
            content=b"",
            headers={
                "content-length": "129",
                "content-type": "multipart/form-data; boundary=limit",
            },
        )

    get_settings.cache_clear()
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Material upload request body is too large"}


def test_material_upload_rejects_oversized_chunked_stream_with_413(monkeypatch) -> None:
    chunks_sent: list[int] = []
    body = (
        b"--limit\r\n"
        b'Content-Disposition: form-data; name="file"; filename="large.txt"\r\n'
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        + b"x" * 96
        + b"\r\n--limit--\r\n"
    )

    def body_chunks() -> Iterator[bytes]:
        for offset in range(0, len(body), 48):
            chunk = body[offset : offset + 48]
            chunks_sent.append(len(chunk))
            yield chunk

    with create_limited_client(monkeypatch) as client:
        response = client.post(
            "/api/courses/course-1/materials",
            content=body_chunks(),
            headers={
                "content-type": "multipart/form-data; boundary=limit",
                "transfer-encoding": "chunked",
            },
        )

    get_settings.cache_clear()
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Material upload request body is too large"}
    assert len(chunks_sent) > 1


def test_upload_request_limit_does_not_affect_other_routes(monkeypatch) -> None:
    with create_limited_client(monkeypatch) as client:
        response = client.post(
            "/api/health",
            content=b"x" * 129,
            headers={"content-length": "129"},
        )

    get_settings.cache_clear()
    assert response.status_code == 405
