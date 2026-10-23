from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from url_shortener.api.deps import get_current_user
from url_shortener.core.database import get_session
from url_shortener.core.security import create_access_token
from url_shortener.models.user import User
from url_shortener.schemas.auth import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from url_shortener.services.auth import (
    UserAlreadyExistsError,
    authenticate_user,
    register_user,
)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    request: UserRegisterRequest,
    session: Session = Depends(get_session),
) -> UserResponse:
    try:
        user = register_user(
            session=session,
            email=request.email,
            password=request.password,
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists.",
        ) from exc

    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login(
    request: UserLoginRequest,
    session: Session = Depends(get_session),
) -> TokenResponse:
    user = authenticate_user(
        session=session,
        email=request.email,
        password=request.password,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(data={"sub": str(user.id), "email": user.email})
    return TokenResponse(access_token=token)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    return UserResponse.model_validate(current_user)
