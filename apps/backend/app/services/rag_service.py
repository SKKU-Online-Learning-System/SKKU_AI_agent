from time import perf_counter

from app.core.config import get_settings
from app.schemas import ChatResponse


class RAGService:
    """Thin boundary between HTTP handlers and the independent AI/RAG package."""

    def __init__(self) -> None:
        self.settings = get_settings()

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
