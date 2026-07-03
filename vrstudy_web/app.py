from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .accounts import authenticate, ensure_user_dirs, session_secret_path
from .data import user_dashboard
from .security import ensure_session_secret, sign_session, verify_session


COOKIE_NAME = "vrstudy_session"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class LoginRequest(BaseModel):
    username: str
    password: str


app = FastAPI(title="VR Study Web")
ensure_user_dirs()
SESSION_SECRET = ensure_session_secret(session_secret_path())
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


def current_username(request: Request) -> str:
    username = verify_session(SESSION_SECRET, request.cookies.get(COOKIE_NAME))
    if username is None:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    return username


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/me")
def me(username: str = Depends(current_username)) -> dict[str, str]:
    return {"username": username}


@app.post("/api/login")
def login(payload: LoginRequest, response: Response) -> dict[str, str]:
    user = authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 맞지 않습니다.")
    response.set_cookie(
        COOKIE_NAME,
        sign_session(SESSION_SECRET, user.username),
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 12,
    )
    return {"username": user.username}


@app.post("/api/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(username: str = Depends(current_username)) -> dict[str, object]:
    return user_dashboard(username)

