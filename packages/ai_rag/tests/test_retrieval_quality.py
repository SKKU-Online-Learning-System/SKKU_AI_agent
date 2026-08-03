import asyncio

from skku_ai_rag.embeddings import LocalHashEmbeddingProvider
from skku_ai_rag.vector_store import InMemoryVectorStore, VectorRecord


def test_local_embedding_prefers_relevant_korean_chunk_and_filters_course() -> None:
    provider = LocalHashEmbeddingProvider(dim=512)
    texts = [
        "경사하강법은 손실 함수의 기울기를 따라 모델 파라미터를 반복해서 갱신한다.",
        "과적합은 훈련 데이터에 지나치게 맞춰져 새로운 데이터의 성능이 낮아지는 현상이다.",
        "경사하강법 학습률과 미니배치 설정은 외부 과목 비공개 자료다.",
    ]
    embeddings = asyncio.run(provider.embed(texts))
    store = InMemoryVectorStore()
    asyncio.run(
        store.upsert(
            [
                VectorRecord("gradient", "course-ai", "m1", texts[0], embeddings[0]),
                VectorRecord("overfit", "course-ai", "m1", texts[1], embeddings[1]),
                VectorRecord("secret", "course-other", "m2", texts[2], embeddings[2]),
            ]
        )
    )

    query = asyncio.run(provider.embed(["경사하강법이 뭐야?"]))[0]
    hits = asyncio.run(store.search("course-ai", query, top_k=5))

    assert hits[0].record.id == "gradient"
    assert hits[0].score > hits[1].score
    assert {hit.record.course_id for hit in hits} == {"course-ai"}
