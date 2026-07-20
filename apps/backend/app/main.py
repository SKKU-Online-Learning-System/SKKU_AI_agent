from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, chat, courses, health, materials
from app.core.config import get_settings
from app.middleware.upload_request_limit import UploadRequestSizeLimitMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SKKU Course Agent API",
        version="0.1.0",
        description="Course-scoped RAG chatbot API for the MVP phase.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        UploadRequestSizeLimitMiddleware,
        max_body_size=settings.max_upload_request_size_bytes,
    )

    app.include_router(health.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(courses.router, prefix="/api")
    app.include_router(materials.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")

    @app.get("/", tags=["root"])
    async def root() -> dict[str, str]:
        return {"service": "skku-course-agent-api", "docs": "/docs"}

    return app


app = create_app()
