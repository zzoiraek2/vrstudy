from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .accounts import (
    authenticate,
    authenticate_remember_token,
    change_password,
    ensure_user_dirs,
    issue_remember_token,
    load_users,
    revoke_remember_token,
    session_secret_path,
)
from .data import (
    create_infinite_web_profile,
    create_vr_web_profile,
    delete_infinite_web_profile,
    delete_vr_web_profile,
    dashboard_infinite_chart,
    dashboard_vr_chart,
    execute_infinite_web_orders,
    execute_vr_web_orders,
    get_kiwoom_credentials,
    get_infinite_schedule,
    get_telegram_settings,
    get_vr_schedule,
    infinite_profile_detail,
    infinite_profiles,
    list_kiwoom_credentials,
    lookup_infinite_balance,
    lookup_infinite_execution_preview,
    lookup_vr_fill_history,
    lookup_vr_period_preview,
    preview_vr_web_orders,
    put_infinite_schedule,
    put_kiwoom_credentials,
    put_telegram_settings,
    put_vr_schedule,
    rename_infinite_web_profile,
    rename_vr_web_profile,
    run_due_market_data_refresh,
    run_due_infinite_schedules,
    run_due_telegram_schedules,
    run_due_vr_schedules,
    save_infinite_web_execution,
    save_vr_web_cycle_input,
    send_telegram_selected_message,
    send_telegram_test_message,
    test_kiwoom_token,
    toggle_infinite_web_profile_pause,
    toggle_vr_web_profile_pause,
    update_infinite_web_profile,
    update_vr_web_profile,
    user_dashboard,
    vr_profile_detail,
    vr_profiles,
)
from .security import ensure_session_secret, sign_session, verify_session


COOKIE_NAME = "vrstudy_session"
REMEMBER_COOKIE_NAME = "vrstudy_remember"
SESSION_MAX_AGE = 60 * 60 * 12
REMEMBER_MAX_AGE = 60 * 60 * 24 * 60
WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
VENDOR_DIR = WEB_DIR / "vendor"


class LoginRequest(BaseModel):
    username: str
    password: str
    remember: bool = False


class PasswordChangeRequest(BaseModel):
    current_password: str = ""
    new_password: str = ""


class KiwoomCredentialsRequest(BaseModel):
    investment_type: str = "실전투자"
    account_number: str = ""
    app_key: str = ""
    app_secret: str = ""
    expires_at: str = ""
    memo: str = ""


class TelegramSettingsRequest(BaseModel):
    bot_token: str = ""
    chat_id: str = ""
    auto_send_on_calculation: bool = True
    auto_send_vr_orders: bool = True
    auto_send_infinite_orders: bool = True
    send_order_table: bool = True
    order_row_limit: int = Field(default=10, ge=1, le=100)
    send_due: bool = True
    send_dashboard: bool = True
    send_vr_summary: bool = True
    send_infinite_summary: bool = True
    send_order_status: bool = True
    send_api_order_result: bool = True
    scheduled_send_enabled: bool = False
    scheduled_send_time: str = "08:30"
    scheduled_send_weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    scheduled_last_attempt_date: str = ""
    scheduled_last_run_at: str = ""
    scheduled_last_status: str = ""
    scheduled_last_message: str = ""
    include_paused: bool = False


class ProfileCreateRequest(BaseModel):
    name: str


class ProfileRenameRequest(BaseModel):
    new_name: str


class VrProfileSettingsRequest(BaseModel):
    start_date: str
    start_week_no: int
    symbol: str
    account_number: str = ""
    min_ratio: float
    max_ratio: float
    initial_v: float = 0.0
    initial_pool: float = 0.0
    initial_principal: float = 0.0
    initial_shares: int = 0
    quantity_step: int | None = None
    buy_limit_start_week_no: int | None = None


class InfiniteProfileSettingsRequest(BaseModel):
    account_number: str = ""
    symbol: str
    start_date: str
    initial_principal: float
    initial_cumulative_amount: float = 0.0
    initial_cumulative_qty: int = 0
    target_rate: float
    split_count: int
    fee_rate: float
    mode: str = "기본"


class InfiniteExecutionRequest(BaseModel):
    trade_date: str
    avg_price: float
    buy_qty: int = 0
    sell_qty: int = 0
    cash_flow_amount: float = 0.0


class VrCycleInputRequest(BaseModel):
    cycle_no: int
    close_price: str = ""
    trade_amount: float = 0.0
    shares: int
    dividend: float = 0.0
    contribution_amount: float = 0.0
    g_config: str = ""
    g_start_cycle_no: int | None = None
    buy_limit_config: str = ""
    buy_limit_start_week_no: int | None = None


class VrOrderRequest(BaseModel):
    sell_mode: str = "match_buy"
    sell_row_count: int | None = Field(default=None, ge=0, le=500)
    force_reorder: bool = False


class OrderExecutionRequest(BaseModel):
    force_reorder: bool = False


class InfiniteScheduleRequest(BaseModel):
    enabled: bool = False
    time: str = "15:55"
    mode: str = "after_input"
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])


class VrScheduleRequest(BaseModel):
    enabled: bool = False
    time: str = "15:55"
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])


app = FastAPI(title="VR Study Web")
ensure_user_dirs()
SESSION_SECRET = ensure_session_secret(session_secret_path())
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")
app.mount("/vendor", StaticFiles(directory=VENDOR_DIR), name="vendor")
_SCHEDULER_TASK: asyncio.Task | None = None


async def _infinite_schedule_loop() -> None:
    while True:
        try:
            usernames = list(load_users().keys())
            await asyncio.to_thread(run_due_market_data_refresh, usernames)
            await asyncio.to_thread(run_due_vr_schedules, usernames)
            await asyncio.to_thread(run_due_infinite_schedules, usernames)
            await asyncio.to_thread(run_due_telegram_schedules, usernames)
        except Exception:
            pass
        await asyncio.sleep(30)


@app.on_event("startup")
async def start_infinite_scheduler() -> None:
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK is None or _SCHEDULER_TASK.done():
        _SCHEDULER_TASK = asyncio.create_task(_infinite_schedule_loop())


@app.on_event("shutdown")
async def stop_infinite_scheduler() -> None:
    global _SCHEDULER_TASK
    if _SCHEDULER_TASK is not None:
        _SCHEDULER_TASK.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _SCHEDULER_TASK
        _SCHEDULER_TASK = None


def set_session_cookie(response: Response, username: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sign_session(SESSION_SECRET, username),
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=SESSION_MAX_AGE,
    )


@app.middleware("http")
async def restore_remembered_session(request: Request, call_next):
    session_username = verify_session(SESSION_SECRET, request.cookies.get(COOKIE_NAME))
    remembered_username = None
    if session_username:
        request.state.username = session_username
    else:
        remembered = authenticate_remember_token(
            request.cookies.get(REMEMBER_COOKIE_NAME)
        )
        if remembered is not None:
            remembered_username = remembered.username
            request.state.username = remembered.username
    response = await call_next(request)
    if remembered_username and request.url.path != "/api/logout":
        set_session_cookie(response, remembered_username)
    return response


def current_username(request: Request) -> str:
    username = getattr(request.state, "username", None) or verify_session(
        SESSION_SECRET, request.cookies.get(COOKIE_NAME)
    )
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
    set_session_cookie(response, user.username)
    if payload.remember:
        remember_token = issue_remember_token(user.username)
        if remember_token:
            response.set_cookie(
                REMEMBER_COOKIE_NAME,
                remember_token,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=REMEMBER_MAX_AGE,
            )
    else:
        revoke_remember_token(user.username)
        response.delete_cookie(REMEMBER_COOKIE_NAME)
    return {"username": user.username}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    username = verify_session(SESSION_SECRET, request.cookies.get(COOKIE_NAME))
    remembered = authenticate_remember_token(request.cookies.get(REMEMBER_COOKIE_NAME))
    if username:
        revoke_remember_token(username)
    elif remembered:
        revoke_remember_token(remembered.username)
    response.delete_cookie(COOKIE_NAME)
    response.delete_cookie(REMEMBER_COOKIE_NAME)
    return {"ok": True}


@app.post("/api/account/password")
def api_account_password(
    payload: PasswordChangeRequest,
    response: Response,
    username: str = Depends(current_username),
) -> dict[str, bool]:
    current_password = payload.current_password
    new_password = payload.new_password
    if not current_password:
        raise HTTPException(status_code=400, detail="현재 비밀번호를 입력해 주세요.")
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="새 비밀번호는 8자 이상이어야 합니다.")
    if new_password == current_password:
        raise HTTPException(status_code=400, detail="새 비밀번호가 현재 비밀번호와 같습니다.")
    if not change_password(username, current_password, new_password):
        raise HTTPException(status_code=400, detail="현재 비밀번호가 맞지 않습니다.")
    response.delete_cookie(REMEMBER_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(username: str = Depends(current_username)) -> dict[str, object]:
    return user_dashboard(username)


@app.get("/api/dashboard/charts/vr/{profile_name}")
def api_dashboard_vr_chart(
    profile_name: str, username: str = Depends(current_username)
) -> dict[str, object]:
    return dashboard_vr_chart(username, profile_name)


@app.get("/api/dashboard/charts/infinite/{profile_name}")
def api_dashboard_infinite_chart(
    profile_name: str, username: str = Depends(current_username)
) -> dict[str, object]:
    return dashboard_infinite_chart(username, profile_name)


@app.get("/api/vr/profiles")
def api_vr_profiles(username: str = Depends(current_username)) -> dict[str, object]:
    return {"profiles": vr_profiles(username)}


@app.post("/api/vr/profiles")
def api_vr_profile_create(
    payload: ProfileCreateRequest, username: str = Depends(current_username)
) -> dict[str, object]:
    try:
        return {"profile": create_vr_web_profile(username, payload.name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/vr/profiles/{profile_name}")
def api_vr_profile(
    profile_name: str, username: str = Depends(current_username)
) -> dict[str, object]:
    return vr_profile_detail(username, profile_name)


@app.put("/api/vr/profiles/{profile_name}")
def api_vr_profile_update(
    profile_name: str,
    payload: VrProfileSettingsRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return {"profile": update_vr_web_profile(username, profile_name, payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/vr/profiles/{profile_name}/rename")
def api_vr_profile_rename(
    profile_name: str,
    payload: ProfileRenameRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return {"profile": rename_vr_web_profile(username, profile_name, payload.new_name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/vr/profiles/{profile_name}")
def api_vr_profile_delete(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return delete_vr_web_profile(username, profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vr/profiles/{profile_name}/toggle-pause")
def api_vr_profile_toggle_pause(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return {"profile": toggle_vr_web_profile_pause(username, profile_name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/vr/profiles/{profile_name}/cycle-input")
def api_vr_cycle_input_save(
    profile_name: str,
    payload: VrCycleInputRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return save_vr_web_cycle_input(username, profile_name, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/vr/profiles/{profile_name}/schedule")
def api_vr_schedule_get(
    profile_name: str, username: str = Depends(current_username)
) -> dict[str, object]:
    try:
        return get_vr_schedule(username, profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/vr/profiles/{profile_name}/schedule")
def api_vr_schedule_put(
    profile_name: str,
    payload: VrScheduleRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return put_vr_schedule(username, profile_name, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/infinite/profiles")
def api_infinite_profiles(username: str = Depends(current_username)) -> dict[str, object]:
    return {"profiles": infinite_profiles(username)}


@app.post("/api/infinite/profiles")
def api_infinite_profile_create(
    payload: ProfileCreateRequest, username: str = Depends(current_username)
) -> dict[str, object]:
    try:
        return {"profile": create_infinite_web_profile(username, payload.name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/infinite/profiles/{profile_name}")
def api_infinite_profile(
    profile_name: str, username: str = Depends(current_username)
) -> dict[str, object]:
    return infinite_profile_detail(username, profile_name)


@app.put("/api/infinite/profiles/{profile_name}")
def api_infinite_profile_update(
    profile_name: str,
    payload: InfiniteProfileSettingsRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return {"profile": update_infinite_web_profile(username, profile_name, payload.model_dump())}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/infinite/profiles/{profile_name}/rename")
def api_infinite_profile_rename(
    profile_name: str,
    payload: ProfileRenameRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return {"profile": rename_infinite_web_profile(username, profile_name, payload.new_name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/infinite/profiles/{profile_name}")
def api_infinite_profile_delete(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return delete_infinite_web_profile(username, profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/infinite/profiles/{profile_name}/toggle-pause")
def api_infinite_profile_toggle_pause(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return {"profile": toggle_infinite_web_profile_pause(username, profile_name)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/infinite/profiles/{profile_name}/execution")
def api_infinite_execution_save(
    profile_name: str,
    payload: InfiniteExecutionRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return save_infinite_web_execution(username, profile_name, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/infinite/profiles/{profile_name}/schedule")
def api_infinite_schedule_get(
    profile_name: str, username: str = Depends(current_username)
) -> dict[str, object]:
    try:
        return get_infinite_schedule(username, profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/infinite/profiles/{profile_name}/schedule")
def api_infinite_schedule_put(
    profile_name: str,
    payload: InfiniteScheduleRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return put_infinite_schedule(username, profile_name, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/kiwoom")
def api_kiwoom_list(username: str = Depends(current_username)) -> dict[str, object]:
    return list_kiwoom_credentials(username)


@app.get("/api/kiwoom/{profile_kind}/{profile_name}")
def api_kiwoom_get(
    profile_kind: str,
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    return get_kiwoom_credentials(username, profile_kind, profile_name)


@app.put("/api/kiwoom/{profile_kind}/{profile_name}")
def api_kiwoom_put(
    profile_kind: str,
    profile_name: str,
    payload: KiwoomCredentialsRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    return put_kiwoom_credentials(username, profile_kind, profile_name, payload.model_dump())


@app.post("/api/kiwoom/{profile_kind}/{profile_name}/token-test")
def api_kiwoom_token_test(
    profile_kind: str,
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    return test_kiwoom_token(username, profile_kind, profile_name)


@app.post("/api/kiwoom/infinite/{profile_name}/execution-preview")
def api_infinite_execution_preview(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return lookup_infinite_execution_preview(username, profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/kiwoom/infinite/{profile_name}/balance")
def api_infinite_balance(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    return lookup_infinite_balance(username, profile_name)


@app.post("/api/kiwoom/infinite/{profile_name}/execute-orders")
def api_infinite_execute_orders(
    profile_name: str,
    payload: OrderExecutionRequest | None = None,
    username: str = Depends(current_username),
) -> dict[str, object]:
    payload = payload or OrderExecutionRequest()
    return execute_infinite_web_orders(
        username, profile_name, force_reorder=payload.force_reorder
    )


@app.post("/api/kiwoom/vr/{profile_name}/execute-orders")
def api_vr_execute_orders(
    profile_name: str,
    payload: VrOrderRequest | None = None,
    username: str = Depends(current_username),
) -> dict[str, object]:
    payload = payload or VrOrderRequest()
    return execute_vr_web_orders(
        username,
        profile_name,
        sell_mode=payload.sell_mode,
        sell_row_count=payload.sell_row_count,
        force_reorder=payload.force_reorder,
    )


@app.post("/api/kiwoom/vr/{profile_name}/order-preview")
def api_vr_order_preview(
    profile_name: str,
    payload: VrOrderRequest | None = None,
    username: str = Depends(current_username),
) -> dict[str, object]:
    payload = payload or VrOrderRequest()
    return preview_vr_web_orders(
        username,
        profile_name,
        sell_mode=payload.sell_mode,
        sell_row_count=payload.sell_row_count,
    )


@app.post("/api/kiwoom/vr/{profile_name}/fill-history/{period_kind}")
def api_vr_fill_history(
    profile_name: str,
    period_kind: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return lookup_vr_fill_history(username, profile_name, period_kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/kiwoom/vr/{profile_name}/period-preview")
def api_vr_period_preview(
    profile_name: str,
    username: str = Depends(current_username),
) -> dict[str, object]:
    try:
        return lookup_vr_period_preview(username, profile_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/telegram")
def api_telegram_get(username: str = Depends(current_username)) -> dict[str, object]:
    return get_telegram_settings(username)


@app.put("/api/telegram")
def api_telegram_put(
    payload: TelegramSettingsRequest,
    username: str = Depends(current_username),
) -> dict[str, object]:
    return put_telegram_settings(username, payload.model_dump())


@app.post("/api/telegram/test")
def api_telegram_test(username: str = Depends(current_username)) -> dict[str, object]:
    try:
        return send_telegram_test_message(username)
    except Exception as exc:
        return {"ok": False, "message": f"테스트 메시지 실패: {exc}"}


@app.post("/api/telegram/send-selected")
def api_telegram_send_selected(username: str = Depends(current_username)) -> dict[str, object]:
    try:
        return send_telegram_selected_message(username)
    except Exception as exc:
        return {"ok": False, "message": f"선택 항목 전송 실패: {exc}"}
