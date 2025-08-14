from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime, timezone, timedelta
import os, json

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI(title="SeaverStrike Task Logger", version="1.0.1")

Assigned = Literal["Shannon", "Kari", "Sonya", "Michael", "Other"]
Priority = Literal["Mission-Critical", "Tactical", "Can Wait"]

class TaskIn(BaseModel):
    Task: str
    Priority: Priority
    Deadline: str
    Assigned_To: Optional[Assigned] = None  # accepts "Assigned To" via alias

    class Config:
        populate_by_name = True
        fields = {"Assigned_To": "Assigned To"}

SHEET_NAME = os.getenv("SHEET_NAME", "SeaverStrike Task Log")
API_KEY = os.getenv("API_KEY", "")

_scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

_sheet = None  # lazy-initialized

def _now(): return datetime.now(timezone.utc)

def _get_sheet():
    global _sheet
    if _sheet is not None:
        return _sheet
    # ---- lazy init: only runs when endpoint is hit ----
    creds_src = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_src:
        raise HTTPException(status_code=500, detail="GOOGLE_SERVICE_ACCOUNT_JSON not set")
    creds_info = json.loads(creds_src)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, _scope)
    client = gspread.authorize(creds)
    _sheet = client.open(SHEET_NAME).sheet1
    return _sheet

def _dedupe(task: str, deadline: str) -> bool:
    try:
        rows = _get_sheet().get_all_values()[-150:]
        for r in rows[1:]:
            ts, t, _, _, d, *_ = (r + [""] * 6)[:6]
            if t == task and d == deadline:
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if _now() - dt <= timedelta(hours=24):
                        return True
    except Exception:
        return False
    return False

@app.get("/health")
def health():
    # Do not touch Sheets here—just prove the server is alive
    return {"ok": True}

@app.post("/add_task")
def add_task(payload: TaskIn, authorization: Optional[str] = Header(default=None)):
    if API_KEY:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        if authorization.split(" ", 1)[1] != API_KEY:
            raise HTTPException(status_code=403, detail="Invalid token")

    task = payload.Task.strip()
    priority = payload.Priority
    deadline = payload.Deadline.strip()
    assigned_to = (payload.Assigned_To or "Other").strip()

    if deadline and len(deadline) != 10:
        raise HTTPException(status_code=422, detail="Deadline must be YYYY-MM-DD or empty")

    if _dedupe(task, deadline):
        return {"ok": True, "duplicate": True}

    notes = []
    try:
        _get_sheet().append_row([_now().isoformat(), task, assigned_to, priority, deadline, "; ".join(notes)])
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
