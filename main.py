import os
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


BASE_DIR = Path(__file__).resolve().parent
_load_env_file(BASE_DIR / ".env")

LOGIN_URL = os.getenv("LOGIN_URL", "")
CLOCK_IN_URL = os.getenv("CLOCK_IN_URL", "")
DEFAULT_USER_CODE = os.getenv("DEFAULT_USER_CODE", "")
DEFAULT_LATITUDE = os.getenv("DEFAULT_LATITUDE", "")
DEFAULT_LONGITUDE = os.getenv("DEFAULT_LONGITUDE", "")
DEFAULT_LOCATION_ADDRESS = os.getenv("DEFAULT_LOCATION_ADDRESS", "")

app = FastAPI(title="Brainerhub Attendance API")
templates = Jinja2Templates(directory="templates")


class ClockInPayload(BaseModel):
    emailAddress: str
    password: str
    userCode: str | None = None
    latitude: str | None = None
    longitude: str | None = None
    locationAddress: str | None = None


def _call_post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> requests.Response:
    try:
        return requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {exc}") from exc


def _response_body(resp: requests.Response) -> Any:
    try:
        return resp.json() if resp.content else {}
    except ValueError:
        return {"raw": resp.text}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.post("/clock-in")
def clock_in(payload: ClockInPayload) -> dict[str, Any]:
    if not LOGIN_URL or not CLOCK_IN_URL:
        raise HTTPException(
            status_code=500,
            detail="LOGIN_URL and CLOCK_IN_URL must be configured in app/.env",
        )

    request_headers = {"Content-Type": "application/json", "Accept": "application/json"}

    login_payload = {
        "emailAddress": payload.emailAddress,
        "password": payload.password,
    }
    login_resp = _call_post(LOGIN_URL, request_headers, login_payload)
    login_body = _response_body(login_resp)

    token = login_body.get("data") if isinstance(login_body, dict) else None
    token = token.strip() if isinstance(token, str) else ""
    if not token:
        raise HTTPException(
            status_code=401,
            detail={
                "message": "Login failed. Could not fetch token.",
                "login_status_code": login_resp.status_code,
                "login_response": login_body,
            },
        )

    clock_headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    clock_payload = {
        "userCode": payload.userCode or DEFAULT_USER_CODE,
        "latitude": payload.latitude or DEFAULT_LATITUDE,
        "longitude": payload.longitude or DEFAULT_LONGITUDE,
        "locationAddress": payload.locationAddress or DEFAULT_LOCATION_ADDRESS,
    }
    clock_resp = _call_post(CLOCK_IN_URL, clock_headers, clock_payload)
    clock_body = _response_body(clock_resp)

    return {
        "success": bool(clock_resp.ok),
        "login_status_code": login_resp.status_code,
        "clock_in_status_code": clock_resp.status_code,
        "token": token,
        "clock_in_payload_used": clock_payload,
        "response": clock_body,
    }
