from fastapi import APIRouter, Depends

from app.api.deps import require_role
from app.models import UserRole

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_role(UserRole.admin))],
)


@router.get("/stats")
async def get_stats() -> dict[str, int]:
    return {
        "users": 0,
        "courses": 0,
        "materials": 0,
        "chatSessions": 0,
        "chatLogs": 0,
    }
