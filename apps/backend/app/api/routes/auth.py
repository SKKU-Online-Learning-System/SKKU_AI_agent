from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import bearer_headers, get_auth_service, get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas import AuthUserRead, LoginRequest, LoginResponse
from app.services.auth_service import AuthService, InvalidCredentialsError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    session: Annotated[Session, Depends(get_db)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> LoginResponse:
    try:
        result = auth_service.login(session, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers=bearer_headers,
        ) from exc

    return LoginResponse(
        access_token=result.access_token,
        user=AuthUserRead.model_validate(result.user),
    )


@router.get("/me", response_model=AuthUserRead)
def get_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user
