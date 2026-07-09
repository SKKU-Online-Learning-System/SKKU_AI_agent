from skku_ai_rag.config import RagConfig
from skku_ai_rag.vector_store import SearchHit


class AnswerGenerator:
    def __init__(self, config: RagConfig) -> None:
        self.config = config

    async def generate(self, question: str, hits: list[SearchHit]) -> str:
        context = self._format_context(hits)

        if not self.config.openai_api_key:
            return (
                "OpenAI API 키가 설정되지 않아 로컬 스텁 답변을 반환합니다. "
                f"질문: {question}\n\n검색 컨텍스트:\n{context or '검색 결과 없음'}"
            )

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.config.openai_api_key)
        response = await client.chat.completions.create(
            model=self.config.chat_model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a course-specific teaching assistant. "
                        "Answer only from the provided lecture context and mention citations."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question:\n{question}\n\nLecture context:\n{context}",
                },
            ],
        )
        return response.choices[0].message.content or ""

    def _format_context(self, hits: list[SearchHit]) -> str:
        chunks: list[str] = []
        remaining = self.config.max_context_chars

        for hit in hits:
            title = hit.record.metadata.get("title", hit.record.material_id)
            page = hit.record.metadata.get("page")
            header = f"[{title}, page={page}, score={hit.score:.3f}]"
            block = f"{header}\n{hit.record.content}".strip()

            if len(block) > remaining:
                break

            chunks.append(block)
            remaining -= len(block)

        return "\n\n---\n\n".join(chunks)
