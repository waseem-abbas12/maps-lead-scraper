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
import linkedin_engine

load_dotenv()

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "leads@secret2026")
SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-leads-key-998811")
MASTER_FILE = os.getenv("MASTER_FILE", "Master_Leads_Database.csv")
LINKEDIN_MASTER_FILE = os.getenv("LINKEDIN_MASTER_FILE", "LinkedIn_Leads_Database.csv")

def get_allowed_keys() -> set:
    keys = set()
    # Read from environment
    env_codes = os.getenv("INVITATION_CODES", "")
    for c in env_codes.split(","):
        if c.strip():
            keys.add(c.strip().upper())
    # Read from allowed_keys.txt
    if os.path.exists("allowed_keys.txt"):
        try:
            with open("allowed_keys.txt", "r", encoding="utf-8") as f:
                for line in f:
                    clean = line.strip()
                    if clean and not clean.startswith("#"):
                        keys.add(clean.upper())
        except Exception:
            pass
    if not keys:
        keys.add("LEAD-PRO-2026")
    return keys

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
    owners_found: int = 0
    last_log_idx: int = 0

state = ScraperState()

class LinkedInState:
    is_running: bool = False
    stop_event: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None
    logs: List[str] = []
    session_leads: List[dict] = []
    emails_found: int = 0
    phones_found: int = 0
    last_log_idx: int = 0

linkedin_state = LinkedInState()

def get_current_user(request: Request) -> Optional[str]:
    cookie = request.cookies.get("lead_auth_session")
    if not cookie:
        return None
    if cookie == make_token(ADMIN_USERNAME):
        return ADMIN_USERNAME
    for code in get_allowed_keys():
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
    # Check Invitation Code against allowed keys
    if invite_code and invite_code.strip().upper() in get_allowed_keys():
        code_clean = invite_code.strip().upper()
        token = make_token(f"invite_{code_clean}")
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
        "error": "Invalid or unauthorized access key. Access denied."
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
    total_linkedin_leads = 0
    if os.path.exists(LINKEDIN_MASTER_FILE):
        try:
            ldf = pd.read_csv(LINKEDIN_MASTER_FILE)
            total_linkedin_leads = len(ldf)
        except Exception:
            pass
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "username": user,
        "total_leads": total_leads,
        "total_linkedin_leads": total_linkedin_leads
    })

class ScrapeRequest(BaseModel):
    niche: str
    location: str
    max_leads: int = 25
    use_variations: Optional[bool] = True
    variations: Optional[bool] = None

    def get_variations_flag(self) -> bool:
        if self.variations is not None:
            return self.variations
        if self.use_variations is not None:
            return self.use_variations
        return True

async def _start_scraping_handler(req: ScrapeRequest):
    if state.is_running:
        return {"status": "already_running", "message": "A scrape job is already active."}
        
    state.is_running = True
    state.stop_event = asyncio.Event()
    state.logs = []
    state.session_leads = []
    state.emails_found = 0
    state.phones_found = 0
    state.owners_found = 0
    state.last_log_idx = 0

    def append_log(msg: str):
        state.logs.append(msg)

    def append_lead(lead: dict):
        state.session_leads.append(lead)
        email = lead.get("Primary Email / Gmail") or lead.get("Email / Gmail") or ""
        phone = lead.get("Primary Phone") or lead.get("Phone Number") or ""
        owner = lead.get("LinkedIn Owner Name") or ""
        if email and email != "Not Found":
            state.emails_found += 1
        if phone and phone != "Not Found":
            state.phones_found += 1
        if owner and owner not in ("Not Found", "None", ""):
            state.owners_found += 1

    async def worker():
        try:
            await scraper_engine.run_scraper_task(
                niche=req.niche.strip(),
                location=req.location.strip(),
                max_leads_per_query=req.max_leads,
                use_variations=req.get_variations_flag(),
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

@app.post("/api/start")
async def start_scraping(req: ScrapeRequest, user: str = Depends(require_auth)):
    return await _start_scraping_handler(req)

@app.post("/api/scrape")
async def scrape_alias(req: ScrapeRequest, user: str = Depends(require_auth)):
    return await _start_scraping_handler(req)

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
    
    total_db_leads = 0
    if os.path.exists(MASTER_FILE):
        try:
            total_db_leads = len(pd.read_csv(MASTER_FILE))
        except Exception:
            pass

    return {
        "is_running": state.is_running,
        "logs": new_logs,
        "new_logs": new_logs,
        "total_leads_scraped": len(state.session_leads),
        "session_leads_count": len(state.session_leads),
        "emails_found": state.emails_found,
        "emails_found_count": state.emails_found,
        "phones_found": state.phones_found,
        "phones_found_count": state.phones_found,
        "owners_found": state.owners_found,
        "owners_found_count": state.owners_found,
        "total_db_leads": total_db_leads,
        "recent_leads": state.session_leads[-15:] if state.session_leads else []
    }

@app.get("/api/session-leads")
async def get_session_leads(user: str = Depends(require_auth)):
    return state.session_leads[::-1]

@app.get("/api/download-session")
async def download_session_csv(user: str = Depends(require_auth)):
    if not state.session_leads:
        raise HTTPException(status_code=400, detail="No leads scraped in current session yet.")
    df = pd.DataFrame(state.session_leads)
    temp_file = "Current_Session_Leads.csv"
    df.to_csv(temp_file, index=False, encoding="utf-8-sig")
    return FileResponse(path=temp_file, filename="Current_Session_Leads.csv", media_type="text/csv")

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

# ==========================================
# DEDICATED LINKEDIN SCRAPER ENDPOINTS
# ==========================================

class LinkedInScrapeRequest(BaseModel):
    role: str = ""
    industry: str = ""
    location: str = ""
    company: Optional[str] = ""
    max_leads: int = 25
    extract_emails: bool = True

@app.post("/api/linkedin/start")
async def start_linkedin_scraping(req: LinkedInScrapeRequest, user: str = Depends(require_auth)):
    if linkedin_state.is_running:
        return {"status": "already_running", "message": "A LinkedIn scrape job is already active."}

    linkedin_state.is_running = True
    linkedin_state.stop_event = asyncio.Event()
    linkedin_state.logs = []
    linkedin_state.session_leads = []
    linkedin_state.emails_found = 0
    linkedin_state.phones_found = 0
    linkedin_state.last_log_idx = 0

    def append_log(msg: str):
        linkedin_state.logs.append(msg)

    def append_lead(lead: dict):
        linkedin_state.session_leads.append(lead)
        email = lead.get("Email") or ""
        phone = lead.get("Phone") or ""
        if email and email != "Not Found":
            linkedin_state.emails_found += 1
        if phone and phone != "Not Found":
            linkedin_state.phones_found += 1

    async def worker():
        try:
            await linkedin_engine.run_linkedin_scraper(
                role=req.role.strip(),
                industry=req.industry.strip(),
                location=req.location.strip(),
                company=(req.company or "").strip(),
                max_leads=req.max_leads,
                extract_emails=req.extract_emails,
                master_file=LINKEDIN_MASTER_FILE,
                log_fn=append_log,
                lead_fn=append_lead,
                stop_event=linkedin_state.stop_event
            )
        except Exception as e:
            append_log(f"💥 Critical Error: {str(e)}")
        finally:
            linkedin_state.is_running = False

    linkedin_state.task = asyncio.create_task(worker())
    return {"status": "started", "message": "LinkedIn scraper initialized successfully."}

@app.get("/api/linkedin/status")
async def get_linkedin_status(user: str = Depends(require_auth)):
    new_logs = linkedin_state.logs[linkedin_state.last_log_idx:]
    linkedin_state.last_log_idx = len(linkedin_state.logs)
    return {
        "is_running": linkedin_state.is_running,
        "logs": new_logs,
        "session_count": len(linkedin_state.session_leads),
        "emails_found": linkedin_state.emails_found,
        "phones_found": linkedin_state.phones_found,
        "latest_leads": linkedin_state.session_leads[-10:] if linkedin_state.session_leads else []
    }

@app.post("/api/linkedin/stop")
async def stop_linkedin_scraping(user: str = Depends(require_auth)):
    if not linkedin_state.is_running:
        return {"status": "not_running", "message": "No active LinkedIn scraping job."}
    if linkedin_state.stop_event:
        linkedin_state.stop_event.set()
    linkedin_state.is_running = False
    linkedin_state.logs.append("🛑 Stop requested for LinkedIn Scraper.")
    return {"status": "stopped", "message": "LinkedIn scraper stopping..."}

@app.get("/api/linkedin/leads")
async def get_linkedin_leads(user: str = Depends(require_auth)):
    if not os.path.exists(LINKEDIN_MASTER_FILE):
        return []
    try:
        df = pd.read_csv(LINKEDIN_MASTER_FILE)
        return df.tail(100).iloc[::-1].fillna("").to_dict(orient="records")
    except Exception:
        return []

@app.get("/api/linkedin/download")
async def download_linkedin_csv(user: str = Depends(require_auth)):
    if not os.path.exists(LINKEDIN_MASTER_FILE):
        raise HTTPException(status_code=404, detail="No LinkedIn leads database found yet.")
    return FileResponse(
        path=LINKEDIN_MASTER_FILE,
        filename="LinkedIn_Leads_Database.csv",
        media_type="text/csv"
    )

@app.get("/api/linkedin/download-session")
async def download_linkedin_session_csv(user: str = Depends(require_auth)):
    if not linkedin_state.session_leads:
        raise HTTPException(status_code=400, detail="No LinkedIn leads scraped in this session yet.")
    df = pd.DataFrame(linkedin_state.session_leads)
    temp_file = "Current_LinkedIn_Session_Leads.csv"
    df.to_csv(temp_file, index=False, encoding="utf-8-sig")
    return FileResponse(path=temp_file, filename="Current_LinkedIn_Session_Leads.csv", media_type="text/csv")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"Server starting on http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
