import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.dependencies import get_current_user, get_db, get_runtime_settings
from app.models.identity import User, UserRole
from app.schemas.auth import DemoLoginRequest, LoginRequest, TokenResponse, UserView
from app.security import create_access_token, hash_password, verify_password
from app.services.bootstrap import DEMO_USERS, ensure_roles
from app.services.audit import add_audit_event


router = APIRouter()


def to_user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=user.is_active,
        roles=sorted(user.role_names),
        created_at=user.created_at,
    )


def token_response(user: User, settings: Settings) -> TokenResponse:
    token = create_access_token(
        user.id,
        settings.secret_key.get_secret_value(),
        settings.access_token_expire_minutes,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_runtime_settings),
) -> TokenResponse:
    user = db.scalar(
        select(User).where(func.lower(User.email) == payload.identifier.strip().lower())
    )
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    user.last_login_at = datetime.now(timezone.utc)
    add_audit_event(
        db,
        action="auth.login",
        object_type="user",
        object_id=user.id,
        actor_id=user.id,
        request_id=getattr(request.state, "request_id", None),
    )
    db.commit()
    return token_response(user, settings)


@router.post("/demo-login", response_model=TokenResponse)
def demo_login(
    payload: DemoLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_runtime_settings),
) -> TokenResponse:
    if settings.environment == "production":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    role_name = payload.role.value
    roles = ensure_roles(db)
    selected_user: User | None = None
    for email, (display_name, configured_role) in DEMO_USERS.items():
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                email=email,
                display_name=display_name,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                is_active=True,
            )
            db.add(user)
            db.flush()
        if configured_role not in user.role_names:
            db.add(
                UserRole(
                    user_id=user.id,
                    role_id=roles[configured_role].id,
                )
            )
        if configured_role == role_name:
            selected_user = user
    if selected_user is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unknown demo role",
        )
    user = selected_user
    user.is_active = True
    user.last_login_at = datetime.now(timezone.utc)
    add_audit_event(
        db,
        action="auth.demo_login",
        object_type="user",
        object_id=user.id,
        actor_id=user.id,
        request_id=getattr(request.state, "request_id", None),
        payload_summary={"role": role_name, "environment": settings.environment},
    )
    db.commit()
    db.refresh(user)
    return token_response(user, settings)


@router.get("/me", response_model=UserView)
def me(current_user: User = Depends(get_current_user)) -> UserView:
    return to_user_view(current_user)
