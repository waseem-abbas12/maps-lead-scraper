import os
import sys
import asyncio
import hashlib
import pandas as pd
from typing import Optional, List
from fastapi import FastAPI, Request, Response, Form, HTTPException, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from dotenv import load_dotenv

import scraper_engine

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "leads@secret2026")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-leads-key-998811")
MASTER_FILE = os.getenv("MASTER_FILE", "Master_Leads_Database.csv")
INVITATION_CODES = [c.strip().upper() for c in os.getenv("INVITATION_CODES", "LEAD-PRO-2026,VIP2026,ADMIN,LEAD2026").split(",") if c.strip()]

def make_token(username: str) -> str:
    return hashlib.sha256(f"{username}:{SECRET_KEY}".encode()).hexdigest()

app = FastAPI(title="Global Maps Lead Scraper")
templates = Jinja2Templates(directory="templates")

# Global Scraper State
class ScraperState:
    is_running: bool = False
    stop_event: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None
    logs: List[str] = []
    session_leads: List[dict] = []
    emails_found: int = 0
    phones_found: int = 0
    last_log_idx: int = 0

state = ScraperState()

def get_current_user(request: Request) -> Optional[str]:
    cookie = request.cookies.get("lead_auth_session")
    if not cookie:
        return None
    if cookie == make_token(ADMIN_USERNAME):
        return ADMIN_USERNAME
    for code in INVITATION_CODES:
        if cookie == make_token(f"invite_{code}"):
            return f"Member ({code})"
    return None

def require_auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"}
        )
    return user

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in (301, 302, 303, 307) and "Location" in exc.headers:
        return RedirectResponse(url=exc.headers["Location"], status_code=303)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": None})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    invite_code: Optional[str] = Form(None),
    username: Optional[str] = Form(None),
    password: Optional[str] = Form(None)
):
    # Check Invitation Code
    if invite_code and invite_code.strip().upper() in INVITATION_CODES:
        token = make_token(f"invite_{invite_code.strip().upper()}")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            key="lead_auth_session",
            value=token,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            samesite="lax"
        )
        return response

    # Check Username / Password if provided
    if username and password and username.strip() == ADMIN_USERNAME and password.strip() == ADMIN_PASSWORD:
        token = make_token(ADMIN_USERNAME)
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            key="lead_auth_session",
            value=token,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            samesite="lax"
        )
        return response

    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": "Invalid Invitation Code. Please verify your code and try again."
    })

@app.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("lead_auth_session")
    return response

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: str = Depends(require_auth)):
    total_leads = 0
    if os.path.exists(MASTER_FILE):
        try:
            df = pd.read_csv(MASTER_FILE)
            total_leads = len(df)
        except Exception:
            pass
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "username": user,
        "total_leads": total_leads
    })

class ScrapeRequest(BaseModel):
    niche: str
    location: str
    max_leads: int = 25
    use_variations: bool = True

@app.post("/api/start")
async def start_scraping(req: ScrapeRequest, user: str = Depends(require_auth)):
    if state.is_running:
        return {"status": "already_running", "message": "A scrape job is already active."}
        
    state.is_running = True
    state.stop_event = asyncio.Event()
    state.logs = []
    state.session_leads = []
    state.emails_found = 0
    state.phones_found = 0
    state.last_log_idx = 0

    def append_log(msg: str):
        state.logs.append(msg)

    def append_lead(lead: dict):
        state.session_leads.append(lead)
        if lead.get("Email / Gmail") != "Not Found":
            state.emails_found += 1
        if lead.get("Phone Number") != "Not Found":
            state.phones_found += 1

    async def worker():
        try:
            await scraper_engine.run_scraper_task(
                niche=req.niche.strip(),
                location=req.location.strip(),
                max_leads_per_query=req.max_leads,
                use_variations=req.use_variations,
                master_file=MASTER_FILE,
                log_fn=append_log,
                lead_fn=append_lead,
                stop_event=state.stop_event
            )
        except Exception as e:
            append_log(f"💥 Critical Error: {str(e)}")
        finally:
            state.is_running = False

    state.task = asyncio.create_task(worker())
    return {"status": "started", "message": "Scraper initialized successfully."}

@app.post("/api/stop")
async def stop_scraping(user: str = Depends(require_auth)):
    if state.is_running and state.stop_event:
        state.stop_event.set()
        state.logs.append("🛑 Abort signal triggered by user.")
        return {"status": "stopping", "message": "Stop signal sent."}
    return {"status": "not_running", "message": "Scraper is not running."}

@app.get("/api/status")
async def get_status(user: str = Depends(require_auth)):
    new_logs = state.logs[state.last_log_idx:]
    state.last_log_idx = len(state.logs)
    return {
        "is_running": state.is_running,
        "logs": new_logs,
        "total_leads_scraped": len(state.session_leads),
        "emails_found": state.emails_found,
        "phones_found": state.phones_found,
        "recent_leads": state.session_leads[-10:] if state.session_leads else []
    }

@app.get("/api/leads")
async def get_leads(user: str = Depends(require_auth)):
    if not os.path.exists(MASTER_FILE):
        return []
    try:
        df = pd.read_csv(MASTER_FILE)
        records = df.tail(100).iloc[::-1].fillna("").to_dict(orient="records")
        return records
    except Exception as e:
        return []

@app.get("/api/download")
async def download_csv(user: str = Depends(require_auth)):
    if not os.path.exists(MASTER_FILE):
        raise HTTPException(status_code=404, detail="Database file not found yet.")
    return FileResponse(
        path=MASTER_FILE,
        filename="Master_Leads_Database.csv",
        media_type="text/csv"
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"Server starting on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
