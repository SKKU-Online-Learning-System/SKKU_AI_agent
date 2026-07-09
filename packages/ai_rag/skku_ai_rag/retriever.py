from skku_ai_rag.embeddings import EmbeddingProvider
from skku_ai_rag.vector_store import SearchHit, VectorStore


class CourseRetriever:
    def __init__(self, vector_store: VectorStore, embedding_provider: EmbeddingProvider) -> None:
        self.vector_store = vector_store
        self.embedding_provider = embedding_provider

    async def retrieve(self, course_id: str, query: str, top_k: int = 5) -> list[SearchHit]:
        query_embedding = (await self.embedding_provider.embed([query]))[0]
        return await self.vector_store.search(
            course_id=course_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )
