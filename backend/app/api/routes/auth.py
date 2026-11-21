from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies import (
    SESSION_COOKIE,
    check_csrf,
    get_auth_service,
    get_event_service,
    require_user,
)
from app.schemas.api import LoginRequest, PasswordChange, UserRead
from app.services.auth_service import AuthService, User
from app.services.event_service import EventService

router = APIRouter(prefix="/auth", tags=["auth"])


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=UserRead, dependencies=[Depends(check_csrf)])
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
    event_service: EventService = Depends(get_event_service),
) -> UserRead:
    client = _client(request)
    wait = auth_service.throttle.retry_after(client)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed logins, retry in {wait} s",
            headers={"Retry-After": str(wait)},
        )
    user = auth_service.authenticate(payload.username, payload.password)
    if user is None:
        auth_service.throttle.failure(client)
        event_service.record(
            "WARNING", f"Failed login for user {payload.username[:40]!r} from {client}"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong username or password"
        )

    auth_service.throttle.success(client)
    token = auth_service.create_session(user)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=auth_service.settings.session_hours * 3600,
        httponly=True,
        secure=auth_service.settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    event_service.record("INFO", f"User {user.username} logged in from {client}")
    return UserRead(username=user.username, role=user.role)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(check_csrf)])
def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    auth_service.end_session(request.cookies.get(SESSION_COOKIE))
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(require_user)) -> UserRead:
    return UserRead(username=user.username, role=user.role)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    response: Response,
    user: User = Depends(require_user),
    auth_service: AuthService = Depends(get_auth_service),
    event_service: EventService = Depends(get_event_service),
) -> None:
    try:
        changed = auth_service.change_password(user, payload.current_password, payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Current password is wrong"
        )
    # every session is closed, this one included: the user logs in again
    response.delete_cookie(SESSION_COOKIE, path="/")
    event_service.record("INFO", f"Password changed for user {user.username}")
