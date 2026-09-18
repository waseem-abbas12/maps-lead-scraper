import asyncio
import os
import sys
import re
import csv
from urllib.parse import quote, unquote
import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
PHONE_REGEX = re.compile(r'(?:\+?[0-9]{1,4}[ -]?)?\(?([0-9]{2,5})\)?[ -]?([0-9]{3,5})[ -]?([0-9]{3,5})')

LINKEDIN_CSV_FILE = "LinkedIn_Leads_Database.csv"

STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

def parse_linkedin_title(title_text: str):
    """
    Parses Google/Bing search title into Name, Headline/Role, Company.
    Common formats:
    'John Doe - Chief Executive Officer - TechCorp | LinkedIn'
    'Jane Smith - Founder & CEO at RealEstatePro | LinkedIn'
    'Alex Vance - Managing Director | LinkedIn'
    """
    clean = re.sub(r'\s*[-|•]\s*LinkedIn.*$', '', title_text, flags=re.I).strip()
    parts = [p.strip() for p in re.split(r'\s*[-–—|•]\s*', clean) if p.strip()]
    
    name = "LinkedIn Member"
    role = "Decision Maker"
    company = "Industry Professional"

    if len(parts) >= 1:
        name = parts[0]
    if len(parts) >= 2:
        role_comp = parts[1]
        if " at " in role_comp:
            sub = role_comp.split(" at ", 1)
            role = sub[0].strip()
            company = sub[1].strip()
        elif " @ " in role_comp:
            sub = role_comp.split(" @ ", 1)
            role = sub[0].strip()
            company = sub[1].strip()
        else:
            role = role_comp
    if len(parts) >= 3:
        company = parts[2]
        
    return name, role, company

def clean_linkedin_url(raw_url: str) -> str:
    """Extracts clean https://www.linkedin.com/in/username/ URL."""
    m = re.search(r'(https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9.\-_%]+)', raw_url, re.I)
    if m:
        u = m.group(1).split('?')[0].rstrip('/')
        return u
    return raw_url

def extract_contacts_from_text(text: str):
    emails = EMAIL_REGEX.findall(text)
    clean_emails = [e.lower() for e in emails if not any(e.lower().endswith(x) for x in ['.png', '.jpg', '.jpeg', '.svg', '.webp']) and len(e) <= 50]
    
    phones = []
    for match in PHONE_REGEX.finditer(text):
        num = match.group(0).strip()
        if sum(c.isdigit() for c in num) >= 7 and len(num) <= 20:
            phones.append(num)
            
    email = clean_emails[0] if clean_emails else "Not Found"
    phone = phones[0] if phones else "Not Found"
    return email, phone

async def run_linkedin_scraper(
    role: str,
    industry: str,
    location: str,
    company: str = "",
    max_leads: int = 25,
    extract_emails: bool = True,
    master_file: str = LINKEDIN_CSV_FILE,
    log_fn = None,
    lead_fn = None,
    stop_event: asyncio.Event = None
):
    def log(msg: str):
        if log_fn:
            log_fn(msg)
        print(f"[LinkedInScraper] {msg}")

    log(f"🚀 Starting High-Impact LinkedIn Scraper...")
    log(f"🎯 Target: Role='{role or 'Executive'}', Industry='{industry}', Location='{location}'" + (f", Company='{company}'" if company else ""))
    
    seen_urls = set()
    if os.path.exists(master_file):
        try:
            with open(master_file, 'r', encoding='utf-8', errors='ignore') as f:
                reader = csv.DictReader(f)
                for r in reader:
                    if r.get('LinkedIn Profile'):
                        seen_urls.add(r['LinkedIn Profile'].lower())
        except Exception:
            pass

    queries = []
    base_role = f'"{role}"' if role else '("CEO" OR "Founder" OR "Owner" OR "Director")'
    base_ind = f'"{industry}"' if industry else ''
    base_loc = f'"{location}"' if location else ''
    base_comp = f'"{company}"' if company else ''

    # Primary Query
    q1 = f'site:linkedin.com/in/ {base_role} {base_ind} {base_loc} {base_comp}'.strip()
    queries.append(q1)

    # Email enriched query
    if extract_emails:
        q2 = f'site:linkedin.com/in/ {base_role} {base_ind} {base_loc} ("@gmail.com" OR "@outlook.com" OR "email" OR "contact")'.strip()
        queries.append(q2)

    # Alternative variation
    if role and industry:
        q3 = f'site:linkedin.com/in/ {base_ind} {base_role} {base_loc}'.strip()
        if q3 not in queries:
            queries.append(q3)

    scraped_count = 0
    leads_batch = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process'
            ]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        page = await context.new_page()

        for q_idx, q in enumerate(queries, 1):
            if stop_event and stop_event.is_set():
                log("🛑 Scrape cancelled by user.")
                break
            if scraped_count >= max_leads:
                break

            log(f"🔎 Scanning LinkedIn Matrix [{q_idx}/{len(queries)}]: {q}")
            
            # Use Google Search for LinkedIn profiles
            search_url = f"https://www.google.com/search?q={quote(q)}&num=30&hl=en"
            
            try:
                await page.goto(search_url, timeout=45000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)

                # Handle Google Consent popup if it appears
                try:
                    consent = page.locator('button:has-text("Accept all"), button:has-text("I agree"), button[aria-label*="Accept"]')
                    if await consent.count() > 0:
                        await consent.first.click(timeout=2000)
                        await page.wait_for_timeout(1000)
                except Exception:
                    pass

                # Extract search results
                results = await page.locator('div.g, div[data-hveid]').all()
                if not results:
                    # Fallback to general anchors
                    anchors = await page.locator('a[href*="linkedin.com/in/"]').all()
                    log(f"📄 Found {len(anchors)} potential profile links on page.")
                else:
                    log(f"📄 Found {len(results)} search result blocks.")

                for item in results:
                    if stop_event and stop_event.is_set():
                        break
                    if scraped_count >= max_leads:
                        break

                    try:
                        link_el = item.locator('a[href*="linkedin.com/in/"]').first
                        if await link_el.count() == 0:
                            continue
                            
                        raw_href = await link_el.get_attribute('href')
                        if not raw_href:
                            continue
                            
                        clean_url = clean_linkedin_url(raw_href)
                        if not clean_url or clean_url.lower() in seen_urls:
                            continue

                        # Extract Title & Snippet
                        title_el = item.locator('h3').first
                        raw_title = await title_el.inner_text() if await title_el.count() > 0 else "LinkedIn Member"
                        
                        snippet_text = ""
                        try:
                            # snippet usually in div with data-sncf or VwiC3b or em
                            snippet_loc = item.locator('div.VwiC3b, div[style*="-webkit-line-clamp"], div.IsZvec').first
                            if await snippet_loc.count() > 0:
                                snippet_text = await snippet_loc.inner_text()
                        except Exception:
                            pass

                        name, detected_role, detected_comp = parse_linkedin_title(raw_title)
                        email, phone = extract_contacts_from_text(snippet_text + " " + raw_title)

                        lead = {
                            "Full Name": name,
                            "Job Title": detected_role or role or "Executive",
                            "Company": detected_comp or company or industry,
                            "Location": location or "Worldwide",
                            "Email": email,
                            "Phone": phone,
                            "LinkedIn Profile": clean_url,
                            "Target Industry": industry,
                            "Snippet": snippet_text[:180].replace("\n", " ") if snippet_text else "Profile verified on LinkedIn"
                        }

                        seen_urls.add(clean_url.lower())
                        scraped_count += 1
                        leads_batch.append(lead)

                        if lead_fn:
                            lead_fn(lead)

                        log(f"✨ [{scraped_count}/{max_leads}] Extracted: {name} ({lead['Job Title']} @ {lead['Company']}) | Email: {email}")

                    except Exception as item_err:
                        continue

            except Exception as e:
                log(f"⚠️ Search matrix warning: {str(e)[:80]}")
                continue

        await browser.close()

    # Save all leads to CSV
    if leads_batch:
        file_exists = os.path.exists(master_file)
        fieldnames = [
            "Full Name", "Job Title", "Company", "Location", 
            "Email", "Phone", "LinkedIn Profile", "Target Industry", "Snippet"
        ]
        try:
            with open(master_file, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists:
                    writer.writeheader()
                for l in leads_batch:
                    writer.writerow(l)
            log(f"💾 Successfully saved {len(leads_batch)} new LinkedIn leads to {master_file}!")
        except Exception as save_err:
            log(f"⚠️ Error saving to CSV: {save_err}")

    log(f"🎉 LinkedIn Scraping Completed! Total unique leads found: {len(leads_batch)}")
    return leads_batch
