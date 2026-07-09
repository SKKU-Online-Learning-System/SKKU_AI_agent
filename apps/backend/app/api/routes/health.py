from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "appEnv": settings.app_env,
        "vectorDbProvider": settings.vector_db_provider,
        "embeddingDim": settings.vector_db_embedding_dim,
    }
