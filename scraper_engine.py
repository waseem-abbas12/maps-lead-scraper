import asyncio
import os
import sys
import re
from urllib.parse import urljoin, urlparse
import aiohttp
import pandas as pd
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
IGNORE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.woff', '.woff2', '.ttf', '.eot')
IGNORE_DOMAINS = ('sentry.io', 'wixpress.com', 'bootstrap.com', 'example.com', 'domain.com', 'schema.org', 'wordpress.org')

def clean_emails(raw_emails):
    valid = []
    for email in raw_emails:
        email = email.strip().strip('.').lower()
        if any(email.endswith(ext) for ext in IGNORE_EXTENSIONS):
            continue
        if any(dom in email for dom in IGNORE_DOMAINS):
            continue
        if len(email) < 6 or len(email) > 60:
            continue
        valid.append(email)
    
    unique = list(dict.fromkeys(valid))
    unique.sort(key=lambda x: 0 if 'gmail.com' in x else 1)
    return unique

async def extract_emails_from_url(session, url):
    if not url or url == 'Not Found' or 'google.com' in url:
        return 'Not Found'
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    found_emails = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    }
    
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=7), ssl=False) as resp:
            if resp.status == 200:
                text = await resp.text(errors='ignore')
                emails = EMAIL_REGEX.findall(text)
                found_emails.extend(emails)
                
                if not emails:
                    contact_matches = re.findall(r'href=[\'"]([^\'"]*(?:contact|about)[^\'"]*)[\'"]', text, re.I)
                    for c_link in contact_matches[:2]:
                        target = urljoin(url, c_link)
                        try:
                            async with session.get(target, headers=headers, timeout=aiohttp.ClientTimeout(total=5), ssl=False) as c_resp:
                                if c_resp.status == 200:
                                    c_text = await c_resp.text(errors='ignore')
                                    found_emails.extend(EMAIL_REGEX.findall(c_text))
                        except Exception:
                            pass
    except Exception:
        pass
        
    cleaned = clean_emails(found_emails)
    return ', '.join(cleaned) if cleaned else 'Not Found'

def generate_variations(niche, location=''):
    niche = niche.strip()
    location = location.strip()
    
    queries = []
    if location:
        queries.extend([
            f'{niche} in {location}',
            f'best {niche} in {location}',
            f'{niche} services in {location}',
            f'top {niche} in {location}',
            f'{niche} near {location}'
        ])
    else:
        queries.extend([
            niche,
            f'best {niche}',
            f'top {niche}',
            f'{niche} services'
        ])
        
    seen = set()
    unique_queries = []
    for q in queries:
        clean_q = ' '.join(q.split())
        if clean_q not in seen:
            seen.add(clean_q)
            unique_queries.append(clean_q)
            
    return unique_queries

def load_seen_leads(file_path):
    seen = set()
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            if 'Google Maps Link' in df.columns:
                for link in df['Google Maps Link'].dropna():
                    clean = str(link).split('?')[0].split('/data=')[0].strip()
                    if clean:
                        seen.add(clean)
            if 'Business Name' in df.columns and 'Phone Number' in df.columns:
                for _, row in df.iterrows():
                    b_name = str(row.get('Business Name', '')).strip().lower()
                    phone = str(row.get('Phone Number', '')).strip()
                    if b_name and phone != 'Not Found':
                        seen.add(f'{b_name}::{phone}')
        except Exception as e:
            pass
    return seen

def save_lead(lead_data, master_file):
    df = pd.DataFrame([lead_data])
    file_exists = os.path.exists(master_file)
    
    if not file_exists:
        df.to_csv(master_file, index=False, header=True, encoding='utf-8-sig')
    else:
        try:
            existing_cols = pd.read_csv(master_file, nrows=0).columns.tolist()
            if 'Email / Gmail' not in existing_cols:
                old_df = pd.read_csv(master_file)
                merged = pd.concat([old_df, df], ignore_index=True)
                merged.to_csv(master_file, index=False, encoding='utf-8-sig')
                return
        except Exception:
            pass
        df.to_csv(master_file, mode='a', index=False, header=False, encoding='utf-8-sig')

async def run_scraper_task(niche, location, max_leads_per_query=20, use_variations=True, master_file='Master_Leads_Database.csv', log_fn=None, lead_fn=None, stop_event=None):
    def log(msg):
        if log_fn:
            log_fn(msg)
        print(msg)
        
    if use_variations:
        queries = generate_variations(niche, location)
    else:
        queries = [f'{niche} {location}'.strip()]
        
    log(f'🚀 Starting Scraping for: {niche} ({location}) - Total Queries: {len(queries)}')
    seen_leads = load_seen_leads(master_file)
    log(f'📁 Database loaded. {len(seen_leads)} existing businesses indexed for deduplication.')
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        page = await browser.new_page()
        await page.set_extra_http_headers({'Accept-Language': 'en-US,en;q=0.9'})
        
        async with aiohttp.ClientSession() as http_session:
            for q_idx, query in enumerate(queries, 1):
                if stop_event and stop_event.is_set():
                    log('🛑 Scraper stopped by user.')
                    break
                    
                log(f'🔍 Query [{q_idx}/{len(queries)}]: \'{query}\'')
                url = f'https://www.google.com/maps/search/{query.replace(" ", "+")}/'
                
                try:
                    await page.goto(url, timeout=60000)
                    
                    try:
                        consent_btn = page.locator('button[aria-label*="Accept all"], button[aria-label*="Agree"], button:has-text("Accept all")')
                        if await consent_btn.count() > 0:
                            await consent_btn.first.click(timeout=3000)
                            await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                        
                    try:
                        await page.wait_for_selector('a[href*="/maps/place/"]', timeout=15000)
                    except Exception:
                        log(f'⚠️ No results found or timeout for: {query}')
                        continue
                        
                    feed_locator = page.locator('div[role="feed"]').first
                    if await feed_locator.count() > 0:
                        for _ in range(6):
                            await feed_locator.evaluate('el => el.scrollBy(0, 10000)')
                            await page.wait_for_timeout(1200)
                    else:
                        await page.hover('a[href*="/maps/place/"]')
                        for _ in range(6):
                            await page.mouse.wheel(0, 10000)
                            await page.wait_for_timeout(1200)
                            
                    listings = await page.locator('a[href*="/maps/place/"]').all()
                    log(f'📊 Found {len(listings)} businesses. Processing top {max_leads_per_query}...')
                    
                    extracted_basic = []
                    for l in listings[:max_leads_per_query]:
                        name = await l.get_attribute('aria-label')
                        link = await l.get_attribute('href')
                        if name and link:
                            clean_link = link.split('?')[0].split('/data=')[0].strip()
                            if clean_link in seen_leads:
                                continue
                            extracted_basic.append({'name': name.strip(), 'link': link.strip(), 'clean_link': clean_link})
                            
                    log(f'🎯 New unique leads to process: {len(extracted_basic)}')
                    
                    for info in extracted_basic:
                        if stop_event and stop_event.is_set():
                            log('🛑 Stop requested.')
                            break
                            
                        try:
                            await page.goto(info['link'], timeout=30000)
                            await page.wait_for_timeout(1500)
                            
                            # Phone
                            phone = 'Not Found'
                            phone_loc = page.locator('button[data-item-id*="phone"], [data-tooltip*="phone" i], button[aria-label*="Phone:"], button[aria-label*="فون:"]')
                            if await phone_loc.count() > 0:
                                p_text = await phone_loc.first.get_attribute('aria-label')
                                if p_text:
                                    phone = p_text.replace('Phone: ', '').replace('فون: ', '').strip()

                            # Website
                            website = 'Not Found'
                            web_loc = page.locator('a[data-item-id*="authority"], [data-tooltip*="website" i], a[aria-label*="Website:"], a[data-item-id="website"]')
                            if await web_loc.count() > 0:
                                w_href = await web_loc.first.get_attribute('href')
                                if w_href:
                                    website = w_href.strip()

                            # Address
                            address = 'Not Found'
                            addr_loc = page.locator('button[data-item-id*="address"], [data-tooltip*="address" i], button[aria-label*="Address:"], button[aria-label*="پتہ:"]')
                            if await addr_loc.count() > 0:
                                a_text = await addr_loc.first.get_attribute('aria-label')
                                if a_text:
                                    address = a_text.replace('Address: ', '').replace('پتہ: ', '').strip()

                            # Category
                            category = 'Not Found'
                            cat_loc = page.locator('button[jsaction*="category"], div.fontBodyMedium button[jsaction*="category"]').first
                            if await cat_loc.count() > 0:
                                category = (await cat_loc.inner_text()).strip()

                            # Rating & Reviews
                            rating = 'Not Found'
                            reviews_count = '0'
                            rating_loc = page.locator('span[aria-label*="stars"], span[aria-label*="ستارے"]').first
                            if await rating_loc.count() > 0:
                                r_text = await rating_loc.get_attribute('aria-label')
                                if r_text:
                                    rating = r_text.strip()
                                    
                            review_loc = page.locator('span[aria-label*="reviews"], span[aria-label*="ریویوز"], span[aria-label*="ratings"]').first
                            if await review_loc.count() > 0:
                                rev_text = await review_loc.get_attribute('aria-label')
                                if rev_text:
                                    reviews_count = rev_text.strip()

                            # Website Email / Gmail
                            email = 'Not Found'
                            if website != 'Not Found':
                                email = await extract_emails_from_url(http_session, website)

                            lead = {
                                'Search Query': query,
                                'Business Name': info['name'],
                                'Category': category,
                                'Phone Number': phone,
                                'Email / Gmail': email,
                                'Website': website,
                                'Address': address,
                                'Rating': rating,
                                'Reviews Count': reviews_count,
                                'Google Maps Link': info['link']
                            }

                            save_lead(lead, master_file)
                            seen_leads.add(info['clean_link'])
                            if phone != 'Not Found':
                                seen_leads.add(f"{info['name'].lower()}::{phone}")

                            if lead_fn:
                                lead_fn(lead)

                            log(f"✔️ {info['name']} | 📞 {phone} | 📧 {email}")
                        except Exception as e:
                            continue
                            
                except Exception as e:
                    log(f'❌ Error in query: {query} ({e})')
                    
                await asyncio.sleep(2)
                
        await browser.close()
        
    log('🎉 Scraping job completed successfully!')
