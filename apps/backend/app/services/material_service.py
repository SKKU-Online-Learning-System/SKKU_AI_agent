from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from starlette.concurrency import run_in_threadpool

ALLOWED_MATERIAL_EXTENSIONS = frozenset({".pdf", ".pptx", ".docx", ".txt"})
READ_CHUNK_SIZE = 1024 * 1024


class MaterialValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StoredUpload:
    internal_file_name: str
    original_file_name: str
    file_type: str
    file_size: int
    storage_path: Path


async def save_upload(
    file: UploadFile,
    course_id: str,
    upload_dir: str | Path,
    max_size_bytes: int,
) -> StoredUpload:
    original_file_name = Path(file.filename or "").name
    extension = Path(original_file_name).suffix.lower()
    if extension not in ALLOWED_MATERIAL_EXTENSIONS:
        raise MaterialValidationError("Allowed file types: .pdf, .pptx, .docx, .txt")

    internal_file_name = f"{uuid4()}{extension}"
    storage_path = Path(upload_dir) / course_id / internal_file_name
    file_size = 0
    try:
        await run_in_threadpool(storage_path.parent.mkdir, parents=True, exist_ok=True)
        destination = await run_in_threadpool(storage_path.open, "wb")
        try:
            while chunk := await file.read(READ_CHUNK_SIZE):
                file_size += len(chunk)
                if file_size > max_size_bytes:
                    raise MaterialValidationError(
                        f"Uploaded file exceeds the {max_size_bytes} byte limit"
                    )
                await run_in_threadpool(destination.write, chunk)
        finally:
            await run_in_threadpool(destination.close)
        if file_size == 0:
            raise MaterialValidationError("Uploaded file must not be empty")
    except Exception:
        await run_in_threadpool(remove_stored_file, storage_path)
        raise

    return StoredUpload(
        internal_file_name=internal_file_name,
        original_file_name=original_file_name,
        file_type=extension.removeprefix("."),
        file_size=file_size,
        storage_path=storage_path,
    )


def remove_stored_file(path: str | Path) -> None:
    Path(path).unlink(missing_ok=True)
