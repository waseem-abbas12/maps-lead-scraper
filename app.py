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
    expected = make_token(ADMIN_USERNAME)
    if cookie == expected:
        return ADMIN_USERNAME
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
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username.strip() == ADMIN_USERNAME and password.strip() == ADMIN_PASSWORD:
        token = make_token(username.strip())
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            key="lead_auth_session",
            value=token,
            max_age=60 * 60 * 24 * 7, # 7 days
            httponly=True,
            samesite="lax"
        )
        return response
    return templates.TemplateResponse(request=request, name="login.html", context={
        "error": "Invalid username or password. Please try again."
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
    location: str = ""
    max_leads: int = 25
    variations: bool = True

async def background_worker(niche: str, location: str, max_leads: int, variations: bool):
    state.is_running = True
    state.stop_event = asyncio.Event()
    state.logs.clear()
    state.session_leads.clear()
    state.emails_found = 0
    state.phones_found = 0
    state.last_log_idx = 0

    def log_cb(msg: str):
        state.logs.append(msg)

    def lead_cb(lead: dict):
        state.session_leads.append(lead)
        if lead.get("Email / Gmail") and lead.get("Email / Gmail") != "Not Found":
            state.emails_found += 1
        if lead.get("Phone Number") and lead.get("Phone Number") != "Not Found":
            state.phones_found += 1

    try:
        await scraper_engine.run_scraper_task(
            niche=niche,
            location=location,
            max_leads_per_query=max_leads,
            use_variations=variations,
            master_file=MASTER_FILE,
            log_fn=log_cb,
            lead_fn=lead_cb,
            stop_event=state.stop_event
        )
    except Exception as e:
        state.logs.append(f"❌ Worker crashed: {e}")
    finally:
        state.is_running = False

@app.post("/api/scrape")
async def start_scrape(data: ScrapeRequest, user: str = Depends(require_auth)):
    if state.is_running:
        raise HTTPException(status_code=400, detail="A scraping task is already running!")
    
    if not data.niche.strip():
        raise HTTPException(status_code=400, detail="Niche category is required!")
        
    state.task = asyncio.create_task(
        background_worker(data.niche, data.location, data.max_leads, data.variations)
    )
    return {"status": "started", "message": f"Scraping started for {data.niche}"}

@app.post("/api/stop")
async def stop_scrape(user: str = Depends(require_auth)):
    if state.is_running and state.stop_event:
        state.stop_event.set()
        return {"status": "stopping", "message": "Stop signal sent"}
    return {"status": "idle", "message": "No active scraping task"}

@app.get("/api/status")
async def get_status(user: str = Depends(require_auth)):
    new_logs = state.logs[state.last_log_idx:]
    state.last_log_idx = len(state.logs)
    
    total_db_leads = 0
    if os.path.exists(MASTER_FILE):
        try:
            total_db_leads = len(pd.read_csv(MASTER_FILE))
        except Exception:
            pass

    return {
        "is_running": state.is_running,
        "new_logs": new_logs,
        "session_leads_count": len(state.session_leads),
        "emails_found_count": state.emails_found,
        "phones_found_count": state.phones_found,
        "total_db_leads": total_db_leads
    }

@app.get("/api/leads")
async def get_leads(user: str = Depends(require_auth)):
    if not os.path.exists(MASTER_FILE):
        return []
    try:
        df = pd.read_csv(MASTER_FILE)
        # return the latest 100 leads reversed
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
