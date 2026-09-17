"""Rebuild course material vectors/images using the configured Qwen model server.

Run from the repository root with PYTHONPATH=apps/backend and DATABASE_URL set
for the target database. Existing chunks are replaced only after successful inference.
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CourseMaterial, CourseMaterialStatus
from app.services.material_processing_service import MaterialProcessingService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--course-id")
    scope.add_argument("--material-id")
    scope.add_argument("--all", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if settings.embedding_provider != "qwen":
        parser.error("Reindexing requires EMBEDDING_PROVIDER=qwen")
    with SessionLocal() as session:
        query = select(CourseMaterial.id).where(
            CourseMaterial.processing_status != CourseMaterialStatus.processing,
        )
        if args.course_id:
            query = query.where(CourseMaterial.course_id == args.course_id)
        if args.material_id:
            query = query.where(CourseMaterial.id == args.material_id)
        ids = list(session.scalars(query))
    failures = 0
    for index, material_id in enumerate(ids, 1):
        with SessionLocal() as session:
            print(f"{datetime.now(timezone.utc).isoformat()} [{index}/{len(ids)}] {material_id}",
                  flush=True)
            try:
                outcome = MaterialProcessingService(session, settings).process_material(
                    material_id, reprocess=True,
                )
                print(f"completed: {outcome.chunk_count} chunks ({outcome.embedding_model})", flush=True)
            except Exception as exc:
                failures += 1
                print(f"failed: {type(exc).__name__}: {exc}", flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
