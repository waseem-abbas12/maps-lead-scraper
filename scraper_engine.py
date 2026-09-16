import asyncio
import os
import sys
import re
from urllib.parse import urljoin, urlparse
import aiohttp
import pandas as pd
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
PHONE_REGEX = re.compile(r'(?:\+?[0-9]{1,4}[ -]?)?\(?([0-9]{2,5})\)?[ -]?([0-9]{3,5})[ -]?([0-9]{3,5})')

IGNORE_EMAIL_EXTS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.woff', '.woff2', '.ttf', '.eot')
IGNORE_DOMAINS = ('sentry.io', 'wixpress.com', 'bootstrap.com', 'example.com', 'domain.com', 'schema.org', 'wordpress.org')

STANDARD_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5'
}

def clean_emails(raw_emails):
    valid = []
    for email in raw_emails:
        email = email.strip().strip('.').lower()
        if any(email.endswith(ext) for ext in IGNORE_EMAIL_EXTS):
            continue
        if any(dom in email for dom in IGNORE_DOMAINS):
            continue
        if len(email) < 6 or len(email) > 60:
            continue
        valid.append(email)
    unique = list(dict.fromkeys(valid))
    unique.sort(key=lambda x: 0 if 'gmail.com' in x else 1)
    return unique

def extract_social_links(html):
    socials = {'facebook': '', 'instagram': '', 'linkedin': '', 'pinterest': ''}
    if not html:
        return socials
        
    fb = re.findall(r'https?://(?:www\.)?facebook\.com/(?:pages/)?([a-zA-Z0-9.\-_/]+)', html, re.I)
    if fb:
        clean_fb = [u for u in fb if not any(x in u.lower() for x in ['sharer', 'share.php', 'plugins', 'tr?id'])]
        if clean_fb:
            socials['facebook'] = f"https://facebook.com/{clean_fb[0].strip('/')}"
            
    insta = re.findall(r'https?://(?:www\.)?instagram\.com/([a-zA-Z0-9._]+)', html, re.I)
    if insta:
        clean_insta = [u for u in insta if u.lower() not in ['p', 'reel', 'stories', 'explore']]
        if clean_insta:
            socials['instagram'] = f"https://instagram.com/{clean_insta[0].strip('/')}"
            
    linkedin = re.findall(r'https?://(?:www\.)?linkedin\.com/(?:company|in)/([a-zA-Z0-9.\-_/]+)', html, re.I)
    if linkedin:
        socials['linkedin'] = f"https://linkedin.com/{linkedin[0].strip('/')}"
        
    pin = re.findall(r'https?://(?:www\.)?pinterest\.com/([a-zA-Z0-9._]+)', html, re.I)
    if pin:
        socials['pinterest'] = f"https://pinterest.com/{pin[0].strip('/')}"
        
    return socials

async def crawl_website_deep(session, url):
    data = {
        'emails': [],
        'phones': [],
        'socials': {'facebook': '', 'instagram': '', 'linkedin': '', 'pinterest': ''},
        'team_leads': []
    }
    if not url or url == 'Not Found' or 'google.com' in url:
        return data
        
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    try:
        async with session.get(url, headers=STANDARD_HEADERS, timeout=aiohttp.ClientTimeout(total=8), ssl=False) as resp:
            if resp.status == 200:
                html = await resp.text(errors='ignore')
                data['emails'].extend(EMAIL_REGEX.findall(html))
                data['socials'] = extract_social_links(html)
                
                # Check /contact, /about, /team
                contact_matches = re.findall(r'href=[\'"]([^\'"]*(?:contact|about|team|leadership)[^\'"]*)[\'"]', html, re.I)
                for c_link in contact_matches[:3]:
                    target = urljoin(url, c_link)
                    try:
                        async with session.get(target, headers=STANDARD_HEADERS, timeout=aiohttp.ClientTimeout(total=5), ssl=False) as c_resp:
                            if c_resp.status == 200:
                                c_html = await c_resp.text(errors='ignore')
                                data['emails'].extend(EMAIL_REGEX.findall(c_html))
                                # update any missing social links
                                sub_socials = extract_social_links(c_html)
                                for k, v in sub_socials.items():
                                    if not data['socials'].get(k) and v:
                                        data['socials'][k] = v
                                        
                                # Look for owner/founder names on /team or /about
                                if any(w in target.lower() for w in ['team', 'leadership', 'about']):
                                    soup = BeautifulSoup(c_html, 'html.parser')
                                    for h in soup.find_all(['h2', 'h3', 'h4', 'strong', 'p']):
                                        t = h.get_text()
                                        if any(role in t.lower() for role in ['founder', 'owner', 'ceo', 'director', 'principal']):
                                            data['team_leads'].append(t.strip())
                    except Exception:
                        pass
    except Exception:
        pass
        
    data['emails'] = clean_emails(data['emails'])
    return data

async def scrape_facebook_page(session, fb_url):
    fb_data = {'phones': [], 'emails': [], 'source': 'Facebook Page'}
    if not fb_url or 'facebook.com' not in fb_url:
        return fb_data
    try:
        async with session.get(fb_url, headers=STANDARD_HEADERS, timeout=aiohttp.ClientTimeout(total=6), ssl=False) as resp:
            if resp.status == 200:
                text = await resp.text(errors='ignore')
                emails = clean_emails(EMAIL_REGEX.findall(text))
                fb_data['emails'].extend(emails)
                # Check for phone numbers or WhatsApp links
                wa_matches = re.findall(r'wa\.me/([0-9+]+)', text)
                if wa_matches:
                    fb_data['phones'].extend(wa_matches)
    except Exception:
        pass
    return fb_data

async def scrape_instagram_bio(session, insta_url):
    insta_data = {'phones': [], 'emails': [], 'source': 'Instagram Bio'}
    if not insta_url or 'instagram.com' not in insta_url:
        return insta_data
    try:
        async with session.get(insta_url, headers=STANDARD_HEADERS, timeout=aiohttp.ClientTimeout(total=6), ssl=False) as resp:
            if resp.status == 200:
                text = await resp.text(errors='ignore')
                emails = clean_emails(EMAIL_REGEX.findall(text))
                insta_data['emails'].extend(emails)
    except Exception:
        pass
    return insta_data

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
    unique = []
    for q in queries:
        clean = ' '.join(q.split())
        if clean not in seen:
            seen.add(clean)
            unique.append(clean)
    return unique

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
            if 'Business Name' in df.columns and 'Primary Phone' in df.columns:
                for _, row in df.iterrows():
                    b_name = str(row.get('Business Name', '')).strip().lower()
                    phone = str(row.get('Primary Phone', '')).strip()
                    if b_name and phone != 'Not Found':
                        seen.add(f'{b_name}::{phone}')
        except Exception:
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
            if 'Keyword Rank' not in existing_cols:
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

    log(f'🚀 Multi-Platform Scraper Initialized: {niche} ({location}) - Total Queries: {len(queries)}')
    seen_leads = load_seen_leads(master_file)
    log(f'📁 Database indexed with {len(seen_leads)} existing records for duplicate prevention.')

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
                    log('🛑 Scraping process stopped by user.')
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
                        log(f'⚠️ No listings found for: {query}')
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
                    log(f'📊 Found {len(listings)} businesses on Google Maps. Processing top {max_leads_per_query}...')

                    extracted_basic = []
                    for rank_idx, l in enumerate(listings[:max_leads_per_query], 1):
                        name = await l.get_attribute('aria-label')
                        link = await l.get_attribute('href')
                        if name and link:
                            clean_link = link.split('?')[0].split('/data=')[0].strip()
                            if clean_link in seen_leads:
                                continue
                            extracted_basic.append({
                                'rank': f'#{rank_idx}',
                                'name': name.strip(),
                                'link': link.strip(),
                                'clean_link': clean_link
                            })

                    log(f'🎯 New unique leads to enrich: {len(extracted_basic)}')

                    for item in extracted_basic:
                        if stop_event and stop_event.is_set():
                            log('🛑 Stop requested.')
                            break

                        try:
                            await page.goto(item['link'], timeout=30000)
                            await page.wait_for_timeout(1500)

                            # 1. Primary Phone (Google Maps)
                            phone = 'Not Found'
                            phone_source = 'None'
                            phone_loc = page.locator('button[data-item-id*="phone"], [data-tooltip*="phone" i], button[aria-label*="Phone:"], button[aria-label*="فون:"]')
                            if await phone_loc.count() > 0:
                                p_text = await phone_loc.first.get_attribute('aria-label')
                                if p_text:
                                    phone = p_text.replace('Phone: ', '').replace('فون: ', '').strip()
                                    phone_source = 'Google Maps'

                            # 2. Website
                            website = 'Not Found'
                            web_loc = page.locator('a[data-item-id*="authority"], [data-tooltip*="website" i], a[aria-label*="Website:"], a[data-item-id="website"]')
                            if await web_loc.count() > 0:
                                w_href = await web_loc.first.get_attribute('href')
                                if w_href:
                                    website = w_href.strip()

                            # 3. Address
                            address = 'Not Found'
                            addr_loc = page.locator('button[data-item-id*="address"], [data-tooltip*="address" i], button[aria-label*="Address:"], button[aria-label*="پتہ:"]')
                            if await addr_loc.count() > 0:
                                a_text = await addr_loc.first.get_attribute('aria-label')
                                if a_text:
                                    address = a_text.replace('Address: ', '').replace('پتہ: ', '').strip()

                            # 4. Category
                            category = 'Not Found'
                            cat_loc = page.locator('button[jsaction*="category"], div.fontBodyMedium button[jsaction*="category"]').first
                            if await cat_loc.count() > 0:
                                category = (await cat_loc.inner_text()).strip()

                            # 5. Rating & Reviews
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

                            # 6. Deep Crawl Website & Social Media
                            sec_phones = []
                            sec_phone_sources = []
                            emails = []
                            email_sources = []
                            fb_url = ''
                            insta_url = ''
                            linkedin_url = ''
                            owner_name = 'Not Found'
                            owner_title = 'Not Found'
                            owner_email = 'Not Found'

                            if website != 'Not Found':
                                web_data = await crawl_website_deep(http_session, website)
                                if web_data['emails']:
                                    emails.extend(web_data['emails'])
                                    email_sources.append('Website')

                                fb_url = web_data['socials'].get('facebook', '')
                                insta_url = web_data['socials'].get('instagram', '')
                                linkedin_url = web_data['socials'].get('linkedin', '')

                                if web_data['team_leads']:
                                    owner_name = web_data['team_leads'][0][:60]
                                    owner_title = 'Executive / Lead'

                                # Enrich with Facebook Page
                                if fb_url:
                                    fb_info = await scrape_facebook_page(http_session, fb_url)
                                    if fb_info['phones']:
                                        sec_phones.extend(fb_info['phones'])
                                        sec_phone_sources.append('Facebook Page')
                                    if fb_info['emails']:
                                        emails.extend(fb_info['emails'])
                                        email_sources.append('Facebook Page')

                                # Enrich with Instagram
                                if insta_url:
                                    insta_info = await scrape_instagram_bio(http_session, insta_url)
                                    if insta_info['emails']:
                                        emails.extend(insta_info['emails'])
                                        email_sources.append('Instagram Bio')

                            # Clean and consolidate
                            final_emails = clean_emails(emails)
                            primary_email = final_emails[0] if final_emails else 'Not Found'
                            primary_email_source = email_sources[0] if (final_emails and email_sources) else 'None'
                            
                            # Check for Owner email specifically
                            if len(final_emails) > 1 and any('gmail.com' in e for e in final_emails):
                                for e in final_emails:
                                    if 'gmail.com' in e and e != primary_email:
                                        owner_email = e
                                        break

                            lead = {
                                'Keyword Rank': item['rank'],
                                'Search Query': query,
                                'Business Name': item['name'],
                                'Category': category,
                                'Primary Phone': phone,
                                'Phone Source': phone_source,
                                'Secondary Phones': ', '.join(list(dict.fromkeys(sec_phones))) if sec_phones else 'Not Found',
                                'Secondary Phone Sources': ', '.join(list(dict.fromkeys(sec_phone_sources))) if sec_phone_sources else 'None',
                                'Primary Email / Gmail': primary_email,
                                'Email Source': primary_email_source,
                                'LinkedIn Owner Name': owner_name,
                                'LinkedIn Owner Email': owner_email,
                                'Website': website,
                                'Facebook': fb_url if fb_url else 'Not Found',
                                'Instagram': insta_url if insta_url else 'Not Found',
                                'LinkedIn': linkedin_url if linkedin_url else 'Not Found',
                                'Address': address,
                                'GMB Rating': rating,
                                'GMB Reviews Count': reviews_count,
                                'Google Maps Link': item['link']
                            }

                            save_lead(lead, master_file)
                            seen_leads.add(item['clean_link'])
                            if phone != 'Not Found':
                                seen_leads.add(f"{item['name'].lower()}::{phone}")

                            if lead_fn:
                                lead_fn(lead)

                            log(f"✔️ [{item['rank']}] {item['name']} | 📞 {phone} ({phone_source}) | 📧 {primary_email} ({primary_email_source})")

                        except Exception as e:
                            continue

                except Exception as e:
                    log(f'❌ Query error: {query} ({e})')

                await asyncio.sleep(2)

        await browser.close()

    log('🎉 Multi-Platform Lead Scraping completed successfully!')
