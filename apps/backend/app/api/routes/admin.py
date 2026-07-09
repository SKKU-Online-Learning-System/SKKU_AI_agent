from fastapi import APIRouter

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def get_stats() -> dict[str, int]:
    return {
        "users": 0,
        "courses": 0,
        "materials": 0,
        "chatSessions": 0,
        "chatLogs": 0,
    }
