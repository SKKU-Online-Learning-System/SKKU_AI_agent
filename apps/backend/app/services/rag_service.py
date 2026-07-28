from time import perf_counter
from typing import Optional

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.schemas import ChatResponse, RAGSearchResult
from app.services.embedding_service import create_embedding_service
from app.services.vector_store_service import VectorStoreService, create_vector_store_service


class RAGSearchError(Exception):
    pass


class RAGService:
    """Thin boundary between HTTP handlers and the independent AI/RAG package."""

    def __init__(
        self,
        session: Optional[Session] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.vector_store: Optional[VectorStoreService] = (
            create_vector_store_service(session, self.settings) if session else None
        )

    def search(self, course_id: str, question: str, top_k: int) -> list[RAGSearchResult]:
        if self.vector_store is None:
            raise RAGSearchError("RAG search requires a database session")
        try:
            query_embedding = create_embedding_service(self.settings).embed_text(question)
            return [
                RAGSearchResult(**result.__dict__)
                for result in self.vector_store.search_similar_chunks(
                    course_id,
                    query_embedding,
                    top_k,
                )
            ]
        except Exception as exc:
            raise RAGSearchError("RAG search failed") from exc

    async def answer(self, course_id: str, question: str) -> ChatResponse:
        started = perf_counter()
        latency_ms = int((perf_counter() - started) * 1000)

        return ChatResponse(
            answer=(
                "아직 실제 검색/생성 파이프라인은 연결되지 않았습니다. "
                f"다음 단계에서 course_id={course_id} 범위의 강의자료 청크를 검색하고 "
                f"질문 '{question}'에 대한 출처 기반 답변을 생성합니다."
            ),
            citations=[],
            latency_ms=latency_ms,
        )
