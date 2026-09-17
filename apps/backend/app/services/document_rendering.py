"""Render complete lecture pages, including charts, shapes and scanned text."""
from __future__ import annotations

import base64
from contextlib import closing, contextmanager
from io import BytesIO
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from threading import Lock
from zipfile import ZipFile
from xml.etree import ElementTree

from app.core.config import Settings
from app.services.document_parser import DocumentParseError, sanitize_text

# PDFium is not thread safe. Serialize rendering, not model requests.
_PDFIUM_LOCK = Lock()


def image_data_url(image: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(image).decode("ascii")


@contextmanager
def material_pdf(path: Path, settings: Settings):
    if path.suffix.lower() == ".pdf":
        yield path
        return
    if path.suffix.lower() not in {".pptx", ".docx"}:
        raise DocumentParseError("지원하지 않는 페이지 렌더링 형식입니다.")
    executable = shutil.which("libreoffice")
    if not executable:
        raise DocumentParseError("PPTX/DOCX 처리를 위해 LibreOffice 설치가 필요합니다.")
    # Do not let a renderer fetch linked images/OLE resources from uploaded files.
    with ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.endswith(".rels"):
                continue
            for relation in ElementTree.fromstring(archive.read(name)):
                if (relation.get("TargetMode") == "External"
                        and not relation.get("Type", "").endswith("/hyperlink")):
                    raise DocumentParseError("외부 연결 개체를 파일 안에 포함한 뒤 업로드해 주세요.")
    with TemporaryDirectory(prefix="course-document-") as directory:
        root = Path(directory)
        profile = root / "profile"
        profile.mkdir()
        # Disable document macros and automatic link updates in an isolated profile.
        (profile / "user").mkdir()
        (profile / "user/registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '</item></oor:items>', encoding="utf-8",
        )
        try:
            subprocess.run(
                [executable, f"-env:UserInstallation={profile.as_uri()}",
                 "--headless", "--convert-to", "pdf", "--outdir", str(root),
                 str(path.resolve())],
                check=True, capture_output=True, timeout=settings.document_conversion_timeout_seconds,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise DocumentParseError("강의 자료 PDF 변환에 실패했습니다.") from exc
        converted = root / (path.stem + ".pdf")
        if not converted.is_file():
            raise DocumentParseError("강의 자료 PDF 변환 결과가 없습니다.")
        yield converted


def render_pages(storage_path: str, settings: Settings):
    """Yield (page number, native text, JPEG bytes); never discard image-only pages."""
    import pypdfium2 as pdfium

    try:
        with material_pdf(Path(storage_path), settings) as path:
            with _PDFIUM_LOCK:
                pdf = pdfium.PdfDocument(path)
                count = len(pdf)
            try:
                if count > settings.document_max_pages:
                    raise DocumentParseError(
                        f"자료는 {settings.document_max_pages}페이지 이하로 나눠 주세요."
                    )
                for index in range(count):
                    with _PDFIUM_LOCK:
                        with closing(pdf[index]) as page:
                            with closing(page.get_textpage()) as text_page:
                                text = sanitize_text(text_page.get_text_range())
                            scale = settings.document_render_max_side / max(page.get_size())
                            with closing(page.render(scale=scale)) as bitmap:
                                with bitmap.to_pil().convert("RGB") as image:
                                    output = BytesIO()
                                    image.save(output, format="JPEG", quality=95)
                    yield index + 1, text, output.getvalue()
            finally:
                with _PDFIUM_LOCK:
                    pdf.close()
    except DocumentParseError:
        raise
    except Exception as exc:
        raise DocumentParseError("강의 자료 페이지를 렌더링할 수 없습니다.") from exc
