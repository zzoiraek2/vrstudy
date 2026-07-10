from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from .kiwoom_credentials import KiwoomCredentials
from .paths import app_data_dir, restrict_private_file


KIWOOM_PROD_HOST = "https://api.kiwoom.com"
KIWOOM_MOCK_HOST = "https://mockapi.kiwoom.com"
TOKEN_REFRESH_BUFFER = timedelta(minutes=10)
KIWOOM_EMPTY_RESULT_CODES = {20, "20"}
US_STOCK_EXCHANGE_CODES = ("ND", "NY", "NA")
US_STOCK_EXCHANGE_FALLBACKS = {
    "TQQQ": "ND",
    "SOXL": "NA",
}


class KiwoomApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        return_code=None,
        return_msg: str = "",
        response_preview: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.return_code = return_code
        self.return_msg = return_msg
        self.response_preview = response_preview


@dataclass(frozen=True)
class KiwoomToken:
    token_type: str = ""
    token: str = ""
    expires_dt: str = ""
    return_code: int | str | None = None
    return_msg: str = ""
    issued_at: str = ""
    host: str = ""
    investment_type: str = ""
    account_number: str = ""


@dataclass(frozen=True)
class KiwoomApiResult:
    body: dict
    headers: dict[str, str]


def kiwoom_token_cache_path() -> Path:
    return app_data_dir() / "secrets" / "kiwoom_token_cache.json"


def kiwoom_host(investment_type: str) -> str:
    investment_type = investment_type or ""
    return (
        KIWOOM_MOCK_HOST
        if "모의" in investment_type or "mock" in investment_type.lower()
        else KIWOOM_PROD_HOST
    )


def issue_access_token(
    credentials: KiwoomCredentials, timeout: int = 15
) -> KiwoomToken:
    app_key = credentials.app_key.strip()
    app_secret = credentials.app_secret.strip()
    if not app_key:
        raise ValueError("App Key가 비어 있습니다.")
    if not app_secret:
        raise ValueError("App Secret이 비어 있습니다.")

    host = kiwoom_host(credentials.investment_type)
    payload = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": app_secret,
    }
    body = _post_json(f"{host}/oauth2/token", payload, timeout=timeout)
    return_code = body.get("return_code")
    return_msg = str(body.get("return_msg") or "")
    if return_code not in (None, 0, "0"):
        raise KiwoomApiError(
            return_msg or "키움 토큰 발급 실패",
            return_code=return_code,
            return_msg=return_msg,
            response_preview=_safe_preview(body),
        )
    token = str(body.get("token") or "")
    if not token:
        raise KiwoomApiError(
            return_msg or "키움 토큰 응답에 token 값이 없습니다.",
            return_code=return_code,
            return_msg=return_msg,
            response_preview=_safe_preview(body),
        )
    return KiwoomToken(
        token_type=str(body.get("token_type") or "bearer"),
        token=token,
        expires_dt=str(body.get("expires_dt") or ""),
        return_code=return_code,
        return_msg=return_msg,
        issued_at=datetime.now().isoformat(timespec="seconds"),
        host=host,
        investment_type=credentials.investment_type,
        account_number=credentials.account_number,
    )


def ensure_access_token(
    profile_kind: str,
    profile_name: str,
    credentials: KiwoomCredentials,
    timeout: int = 15,
) -> tuple[KiwoomToken, bool]:
    token = load_profile_token(profile_kind, profile_name)
    if token and is_token_valid_for_credentials(token, credentials):
        return token, False
    token = issue_access_token(credentials, timeout=timeout)
    save_profile_token(profile_kind, profile_name, token)
    return token, True


def load_profile_token(
    profile_kind: str, profile_name: str, path: Path | None = None
) -> KiwoomToken | None:
    cache = load_token_cache(path)
    raw = cache.get(profile_kind, {}).get(profile_name)
    if not isinstance(raw, dict):
        return None
    allowed = set(KiwoomToken.__dataclass_fields__)
    return KiwoomToken(**{key: value for key, value in raw.items() if key in allowed})


def is_token_valid_for_credentials(
    token: KiwoomToken, credentials: KiwoomCredentials, now: datetime | None = None
) -> bool:
    if not token.token:
        return False
    if token.host and token.host != kiwoom_host(credentials.investment_type):
        return False
    if token.investment_type and token.investment_type != credentials.investment_type:
        return False
    if token.account_number and token.account_number != credentials.account_number:
        return False
    expires_at = parse_kiwoom_datetime(token.expires_dt)
    if expires_at is None:
        return False
    now = now or datetime.now()
    return expires_at > now + TOKEN_REFRESH_BUFFER


def parse_kiwoom_datetime(value: str) -> datetime | None:
    value = str(value or "").strip()
    if not value:
        return None
    for fmt in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def default_us_stock_exchange_code(stk_cd: str) -> str:
    return US_STOCK_EXCHANGE_FALLBACKS.get(str(stk_cd or "").upper(), "ND")


def request_us_stock_exchange_info(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    stk_cd: str,
    timeout: int = 15,
) -> dict:
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {"stk_cd": str(stk_cd or "").upper()}
    result = _post_kiwoom_json(
        f"{host}/api/us/stkinfo",
        payload,
        api_id="usa10098",
        token=token.token,
        timeout=timeout,
    )
    _raise_for_kiwoom_body(result.body)
    body = dict(result.body)
    body["_meta"] = {
        "api_id": "usa10098",
        "headers": result.headers,
        "request": payload,
    }
    return body


def resolve_us_stock_exchange_code(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    stk_cd: str,
    *,
    timeout: int = 15,
) -> str:
    symbol = str(stk_cd or "").upper()
    fallback = default_us_stock_exchange_code(symbol)
    if not symbol:
        return fallback
    try:
        body = request_us_stock_exchange_info(
            credentials, token, stk_cd=symbol, timeout=timeout
        )
    except KiwoomApiError:
        return fallback
    rows: list[dict] = []
    for key in ("list", "result_list", "result_lsit"):
        value = body.get(key)
        if isinstance(value, list):
            rows.extend(row for row in value if isinstance(row, dict))
    for row in rows:
        row_symbol = str(row.get("stk_cd") or "").upper()
        code = str(row.get("stex_tp") or "").upper()
        if code in US_STOCK_EXCHANGE_CODES and row_symbol == symbol:
            return code
    for row in rows:
        code = str(row.get("stex_tp") or "").upper()
        if code in US_STOCK_EXCHANGE_CODES:
            return code
    return fallback


def request_us_stock_quote(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    stex_tp: str,
    stk_cd: str,
    timeout: int = 15,
) -> dict:
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {
        "stex_tp": str(stex_tp or ""),
        "stk_cd": str(stk_cd or "").upper(),
    }
    result = _post_kiwoom_json(
        f"{host}/api/us/mrkcond",
        payload,
        api_id="usa20100",
        token=token.token,
        timeout=timeout,
    )
    _raise_for_kiwoom_body(result.body)
    body = dict(result.body)
    body["_meta"] = {
        "api_id": "usa20100",
        "headers": result.headers,
        "request": payload,
    }
    return body


def request_us_daily_prices(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    stex_tp: str,
    stk_cd: str,
    base_dt: str,
    timeout: int = 15,
    max_pages: int = 3,
) -> dict:
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {
        "stex_tp": str(stex_tp or ""),
        "stk_cd": str(stk_cd or "").upper(),
        "base_dt": str(base_dt or ""),
    }
    pages: list[KiwoomApiResult] = []
    cont_yn = "N"
    next_key = ""
    for _ in range(max_pages):
        result = _post_kiwoom_json(
            f"{host}/api/us/mrkcond",
            payload,
            api_id="usa20590",
            token=token.token,
            cont_yn=cont_yn,
            next_key=next_key,
            timeout=timeout,
        )
        _raise_for_kiwoom_body(result.body)
        pages.append(result)
        next_key = result.headers.get("next-key", "")
        if result.headers.get("cont-yn") != "Y" or not next_key:
            break
        cont_yn = "Y"

    if not pages:
        return {}
    merged = dict(pages[0].body)
    rows: list[dict] = []
    for page in pages:
        for key in ("result_list", "result_lsit"):
            page_rows = page.body.get(key)
            if isinstance(page_rows, list):
                rows.extend(row for row in page_rows if isinstance(row, dict))
                break
    if rows:
        merged["result_list"] = rows
    merged["_meta"] = {
        "api_id": "usa20590",
        "pages": len(pages),
        "last_cont_yn": pages[-1].headers.get("cont-yn", ""),
        "last_next_key": pages[-1].headers.get("next-key", ""),
        "request": payload,
    }
    return merged


def request_us_ledger_balance(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    stex_tp: str = "",
    stk_cd: str = "",
    timeout: int = 15,
    max_pages: int = 10,
) -> dict:
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {
        "stex_tp": str(stex_tp or ""),
        "stk_cd": str(stk_cd or ""),
    }
    pages: list[KiwoomApiResult] = []
    cont_yn = "N"
    next_key = ""
    for _ in range(max_pages):
        result = _post_kiwoom_json(
            f"{host}/api/us/acnt",
            payload,
            api_id="ust21070",
            token=token.token,
            cont_yn=cont_yn,
            next_key=next_key,
            timeout=timeout,
        )
        if result.body.get("return_code") in KIWOOM_EMPTY_RESULT_CODES:
            return _empty_kiwoom_result("ust21070", result)
        _raise_for_kiwoom_body(result.body)
        pages.append(result)
        next_key = result.headers.get("next-key", "")
        if result.headers.get("cont-yn") != "Y" or not next_key:
            break
        cont_yn = "Y"

    if not pages:
        return {}
    merged = dict(pages[0].body)
    if len(pages) > 1:
        rows: list[dict] = []
        for page in pages:
            page_rows = page.body.get("result_list")
            if isinstance(page_rows, list):
                rows.extend(page_rows)
        if rows:
            merged["result_list"] = rows
    merged["_meta"] = {
        "api_id": "ust21070",
        "pages": len(pages),
        "last_cont_yn": pages[-1].headers.get("cont-yn", ""),
        "last_next_key": pages[-1].headers.get("next-key", ""),
    }
    return merged


def request_us_transaction_history(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    start_date: str,
    end_date: str,
    tp: str = "",
    stex_tp: str = "",
    stk_cd: str = "",
    krw_repl_skip_yn: str = "",
    timeout: int = 15,
    max_pages: int = 10,
) -> dict:
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {
        "strt_dt": str(start_date or ""),
        "end_dt": str(end_date or ""),
        "tp": str(tp or ""),
        "stex_tp": str(stex_tp or ""),
        "stk_cd": str(stk_cd or ""),
        "krw_repl_skip_yn": str(krw_repl_skip_yn or ""),
    }
    pages: list[KiwoomApiResult] = []
    cont_yn = "N"
    next_key = ""
    for _ in range(max_pages):
        result = _post_kiwoom_json(
            f"{host}/api/us/acnt",
            payload,
            api_id="ust21100",
            token=token.token,
            cont_yn=cont_yn,
            next_key=next_key,
            timeout=timeout,
        )
        if result.body.get("return_code") in KIWOOM_EMPTY_RESULT_CODES:
            return _empty_kiwoom_result("ust21100", result)
        _raise_for_kiwoom_body(result.body)
        pages.append(result)
        next_key = result.headers.get("next-key", "")
        if result.headers.get("cont-yn") != "Y" or not next_key:
            break
        cont_yn = "Y"

    if not pages:
        return {}
    merged = dict(pages[0].body)
    rows: list[dict] = []
    for page in pages:
        for key in ("result_list", "result_lsit"):
            page_rows = page.body.get(key)
            if isinstance(page_rows, list):
                rows.extend(page_rows)
                break
    if rows:
        merged["result_list"] = rows
    merged["_meta"] = {
        "api_id": "ust21100",
        "pages": len(pages),
        "last_cont_yn": pages[-1].headers.get("cont-yn", ""),
        "last_next_key": pages[-1].headers.get("next-key", ""),
    }
    return merged


def request_us_period_order_history(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    start_date: str,
    end_date: str,
    slby_tp: str = "0",
    stex_tp: str = "",
    stk_cd: str = "",
    oppo_trde_tp: str = "%",
    timeout: int = 15,
    max_pages: int = 10,
) -> dict:
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {
        "strt_dt": str(start_date or ""),
        "end_dt": str(end_date or ""),
        "slby_tp": str(slby_tp or "0"),
        "stex_tp": str(stex_tp or ""),
        "stk_cd": str(stk_cd or ""),
        "oppo_trde_tp": str(oppo_trde_tp or "%"),
    }
    pages: list[KiwoomApiResult] = []
    cont_yn = "N"
    next_key = ""
    for _ in range(max_pages):
        result = _post_kiwoom_json(
            f"{host}/api/us/acnt",
            payload,
            api_id="ust21180",
            token=token.token,
            cont_yn=cont_yn,
            next_key=next_key,
            timeout=timeout,
        )
        if result.body.get("return_code") in KIWOOM_EMPTY_RESULT_CODES:
            return _empty_kiwoom_result("ust21180", result)
        _raise_for_kiwoom_body(result.body)
        pages.append(result)
        next_key = result.headers.get("next-key", "")
        if result.headers.get("cont-yn") != "Y" or not next_key:
            break
        cont_yn = "Y"

    if not pages:
        return {}
    merged = dict(pages[0].body)
    rows: list[dict] = []
    for page in pages:
        for key in ("result_list", "result_lsit"):
            page_rows = page.body.get(key)
            if isinstance(page_rows, list):
                rows.extend(page_rows)
                break
    if rows:
        merged["result_list"] = rows
    merged["_meta"] = {
        "api_id": "ust21180",
        "pages": len(pages),
        "last_cont_yn": pages[-1].headers.get("cont-yn", ""),
        "last_next_key": pages[-1].headers.get("next-key", ""),
    }
    return merged


def request_us_stock_order(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    *,
    side: str,
    stex_tp: str,
    stk_cd: str,
    ord_qty: int | str,
    trde_tp: str,
    ord_uv: float | str | None = None,
    stop_pric: float | str | None = None,
    timeout: int = 15,
) -> dict:
    side = side.lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"Unknown US stock order side: {side}")
    api_id = "ust20000" if side == "buy" else "ust20001"
    host = token.host or kiwoom_host(credentials.investment_type)
    payload = {
        "stex_tp": str(stex_tp or ""),
        "stk_cd": str(stk_cd or "").upper(),
        "ord_qty": str(ord_qty or ""),
        "ord_uv": "" if ord_uv is None else str(ord_uv),
        "trde_tp": str(trde_tp or ""),
    }
    if side == "sell":
        payload["stop_pric"] = "" if stop_pric is None else str(stop_pric)
    result = _post_kiwoom_json(
        f"{host}/api/us/ordr",
        payload,
        api_id=api_id,
        token=token.token,
        timeout=timeout,
    )
    _raise_for_kiwoom_body(result.body)
    body = dict(result.body)
    body["_meta"] = {
        "api_id": api_id,
        "headers": result.headers,
        "request": payload,
    }
    return body


def request_us_buy_order(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    **kwargs,
) -> dict:
    return request_us_stock_order(credentials, token, side="buy", **kwargs)


def request_us_sell_order(
    credentials: KiwoomCredentials,
    token: KiwoomToken,
    **kwargs,
) -> dict:
    return request_us_stock_order(credentials, token, side="sell", **kwargs)


def _post_kiwoom_json(
    url: str,
    payload: dict,
    *,
    api_id: str,
    token: str,
    cont_yn: str = "N",
    next_key: str = "",
    timeout: int,
) -> KiwoomApiResult:
    return _post_json_with_headers(
        url,
        payload,
        timeout=timeout,
        headers={
            "authorization": f"Bearer {token}",
            "cont-yn": cont_yn,
            "next-key": next_key,
            "api-id": api_id,
        },
    )


def _raise_for_kiwoom_body(body: dict) -> None:
    return_code = body.get("return_code")
    return_msg = str(body.get("return_msg") or "")
    if return_code not in (None, 0, "0"):
        raise KiwoomApiError(
            return_msg or "Kiwoom API call failed",
            return_code=return_code,
            return_msg=return_msg,
            response_preview=_safe_preview(body),
        )


def _empty_kiwoom_result(api_id: str, result: KiwoomApiResult) -> dict:
    body = dict(result.body)
    body["result_list"] = []
    body["_meta"] = {
        "api_id": api_id,
        "pages": 1,
        "last_cont_yn": result.headers.get("cont-yn", ""),
        "last_next_key": result.headers.get("next-key", ""),
        "empty_result": True,
    }
    return body


def _post_json(url: str, payload: dict, timeout: int) -> dict:
    return _post_json_with_headers(url, payload, timeout=timeout).body


def _post_json_with_headers(
    url: str,
    payload: dict,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> KiwoomApiResult:
    request_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json;charset=UTF-8",
        "User-Agent": "vrstudy/1.0",
    }
    request_headers.update(headers or {})
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    context = _create_ssl_context()
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            text = response.read().decode("utf-8")
            response_headers = _selected_response_headers(response.headers)
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        parsed = _json_or_empty(text)
        return_msg = (
            str(parsed.get("return_msg") or parsed.get("message") or "")
            if isinstance(parsed, dict)
            else ""
        )
        raise KiwoomApiError(
            return_msg or f"키움 API HTTP 오류: {exc.code}",
            status_code=exc.code,
            return_code=parsed.get("return_code") if isinstance(parsed, dict) else None,
            return_msg=return_msg,
            response_preview=_safe_preview(parsed if parsed else text),
        ) from exc
    except URLError as exc:
        raise KiwoomApiError(f"키움 API 연결 실패: {exc.reason}") from exc
    parsed = _json_or_empty(text)
    if not isinstance(parsed, dict):
        raise KiwoomApiError(
            "키움 API 응답이 JSON 객체가 아닙니다.",
            response_preview=_safe_preview(text),
        )
    return KiwoomApiResult(body=parsed, headers=response_headers)


def _selected_response_headers(headers) -> dict[str, str]:
    return {
        key: str(headers.get(key) or "")
        for key in ("next-key", "cont-yn", "api-id")
        if headers.get(key) is not None
    }


def _create_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=certifi.where())
    if os.name == "nt" and hasattr(ssl, "enum_certificates"):
        _load_windows_trusted_certificates(context)
    return context


def _load_windows_trusted_certificates(context: ssl.SSLContext) -> None:
    server_auth_oid = "1.3.6.1.5.5.7.3.1"
    pem_chunks: list[str] = []
    for store_name in ("ROOT", "CA"):
        try:
            certificates = ssl.enum_certificates(store_name)
        except OSError:
            continue
        for cert_bytes, encoding, trust in certificates:
            if encoding != "x509_asn":
                continue
            if trust is not True and server_auth_oid not in trust:
                continue
            try:
                pem_chunks.append(ssl.DER_cert_to_PEM_cert(cert_bytes))
            except ValueError:
                continue
    if not pem_chunks:
        return
    try:
        context.load_verify_locations(cadata="\n".join(pem_chunks))
    except ssl.SSLError:
        pass


def _json_or_empty(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def _safe_preview(value, limit: int = 240) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = _masked_dict(value)
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    for marker in ("token", "appkey", "secretkey", "authorization"):
        text = _mask_jsonish_value(text, marker)
    return text[:limit]


def _masked_dict(data: dict) -> dict:
    masked = {}
    for key, value in data.items():
        if str(key).lower() in {"token", "appkey", "secretkey", "authorization"}:
            masked[key] = "***"
        else:
            masked[key] = value
    return masked


def _mask_jsonish_value(text: str, marker: str) -> str:
    pattern = f'"{marker}"'
    lower = text.lower()
    idx = lower.find(pattern)
    if idx < 0:
        return text
    colon = text.find(":", idx)
    if colon < 0:
        return text
    quote = text.find('"', colon + 1)
    if quote < 0:
        return text
    end = text.find('"', quote + 1)
    if end < 0:
        return text
    return text[: quote + 1] + "***" + text[end:]


def load_token_cache(path: Path | None = None) -> dict:
    path = path or kiwoom_token_cache_path()
    if not path.exists():
        return {"vr": {}, "infinite": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"vr": {}, "infinite": {}}
    return {
        "vr": dict(data.get("vr") or {}),
        "infinite": dict(data.get("infinite") or {}),
    }


def save_token_cache(data: dict, path: Path | None = None) -> Path:
    path = path or kiwoom_token_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        "vr": dict(data.get("vr") or {}),
        "infinite": dict(data.get("infinite") or {}),
    }
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    restrict_private_file(path)
    return path


def save_profile_token(
    profile_kind: str,
    profile_name: str,
    token: KiwoomToken,
    path: Path | None = None,
) -> Path:
    cache = load_token_cache(path)
    cache.setdefault(profile_kind, {})[profile_name] = asdict(token)
    return save_token_cache(cache, path)


def rename_profile_token(
    profile_kind: str,
    old_name: str,
    new_name: str,
    path: Path | None = None,
) -> Path | None:
    cache = load_token_cache(path)
    profiles = cache.setdefault(profile_kind, {})
    if old_name not in profiles:
        return None
    profiles[new_name] = profiles.pop(old_name)
    return save_token_cache(cache, path)


def delete_profile_token(
    profile_kind: str, profile_name: str, path: Path | None = None
) -> Path | None:
    cache = load_token_cache(path)
    profiles = cache.setdefault(profile_kind, {})
    if profile_name not in profiles:
        return None
    profiles.pop(profile_name, None)
    return save_token_cache(cache, path)
