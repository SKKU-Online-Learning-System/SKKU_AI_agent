from fastapi import APIRouter

from app.core.config import get_settings
from app.services.model_server.client import check_model_server_health

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


@router.get("/health/model-server")
def model_server_health() -> dict[str, object]:
    """Return a best-effort inference health snapshot without gating app startup."""
    settings = get_settings()
    health = check_model_server_health(settings)
    return {
        "status": "ok" if health.all_available else "degraded",
        "llm_provider": settings.effective_llm_provider,
        "voice_provider": settings.voice_provider,
        "services": health.as_dict(),
    }
