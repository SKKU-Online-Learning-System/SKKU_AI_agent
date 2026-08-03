from __future__ import annotations

import argparse
import os
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload, process, and search the sample RAG material through the backend API."
    )
    parser.add_argument(
        "--api-base", default=os.getenv("RAG_API_BASE_URL", "http://localhost:8000")
    )
    parser.add_argument("--email", default=os.getenv("RAG_DEBUG_EMAIL", "professor@skku.edu"))
    parser.add_argument(
        "--password", default=os.getenv("RAG_DEBUG_PASSWORD", "password123")
    )
    parser.add_argument("--course-id")
    parser.add_argument("--question", default="경사하강법이 뭐야?")
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 21))
    parser.add_argument("--sample", type=Path, default=ROOT / "fixtures/rag/ai_intro.txt")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with httpx.Client(base_url=args.api_base.rstrip("/"), timeout=60) as client:
            login = client.post(
                "/api/auth/login", json={"email": args.email, "password": args.password}
            )
            login.raise_for_status()
            client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"

            courses = client.get("/api/courses")
            courses.raise_for_status()
            course_id = args.course_id or (courses.json()[0]["id"] if courses.json() else None)
            if not course_id:
                raise RuntimeError("검색할 담당 과목이 없습니다.")

            with args.sample.open("rb") as sample_file:
                upload = client.post(
                    f"/api/courses/{course_id}/materials",
                    data={"week": "1"},
                    files={"file": (args.sample.name, sample_file, "text/plain")},
                )
            upload.raise_for_status()
            material_id = upload.json()["id"]

            process = client.post(
                f"/api/courses/{course_id}/materials/{material_id}/process"
            )
            process.raise_for_status()
            search = client.post(
                "/api/rag/search",
                json={
                    "course_id": course_id,
                    "question": args.question,
                    "top_k": args.top_k,
                    "debug": True,
                },
            )
            search.raise_for_status()

            body = search.json()
            print(
                f"course={course_id} material={material_id} "
                f"chunks={process.json().get('chunkCount', 0)}"
            )
            print(f"debug={body.get('debug', {})}")
            for index, result in enumerate(body["results"], start=1):
                preview = result["chunk_text"].replace("\n", " ")[:180]
                print(
                    f"{index}. score={result['score']:.4f} "
                    f"document={result['document_name']} chunk={result['chunk_index']} "
                    f"id={result['chunk_id']}\n   {preview}"
                )
            print(f"cleanup: DELETE /api/courses/{course_id}/materials/{material_id}")
            return 0
    except (httpx.HTTPError, OSError, RuntimeError) as exc:
        print(f"RAG smoke test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
