import asyncio
import os
import sys
import re
from urllib.parse import urljoin, urlparse
import aiohttp
import pandas as pd
from playwright.async_api import async_playwright

# ونڈوز کنسول پر اینکوڈنگ کی غلطیوں سے بچاؤ
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ای میلز اور ویب سائٹ کے لیے ریجیکس اور فلٹرز
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
IGNORE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.woff', '.woff2', '.ttf', '.eot')
IGNORE_DOMAINS = ('sentry.io', 'wixpress.com', 'bootstrap.com', 'example.com', 'domain.com', 'schema.org', 'wordpress.org')

def clean_emails(raw_emails):
    """ای میلز کو فلٹر اور صاف کر کے منفرد فہرست بنانا، اور جی میلز کو ترجیح دینا"""
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
    
    unique_emails = list(dict.fromkeys(valid))
    # جی میل ایڈریس کو لسٹ میں سب سے پہلے رکھنا
    unique_emails.sort(key=lambda x: 0 if 'gmail.com' in x else 1)
    return unique_emails

async def extract_emails_from_url(session, url):
    """ویب سائٹ کے ہوم پیج اور کانٹیکٹ پیج سے ای میلز اور جی میل نکالنا"""
    if not url or url == "Not Found" or "google.com" in url:
        return "Not Found"
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
    found_emails = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5'
    }
    
    try:
        # ہوم پیج چیک کرنا
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8), ssl=False) as resp:
            if resp.status == 200:
                text = await resp.text(errors='ignore')
                emails = EMAIL_REGEX.findall(text)
                found_emails.extend(emails)
                
                # اگر ہوم پیج پر ای میل نہ ملے تو Contact / About پیج تلاش کرنا
                if not emails:
                    contact_matches = re.findall(r'href=[\'"]([^\'"]*(?:contact|about)[^\'"]*)[\'"]', text, re.I)
                    for c_link in contact_matches[:2]:
                        target = urljoin(url, c_link)
                        try:
                            async with session.get(target, headers=headers, timeout=aiohttp.ClientTimeout(total=6), ssl=False) as c_resp:
                                if c_resp.status == 200:
                                    c_text = await c_resp.text(errors='ignore')
                                    found_emails.extend(EMAIL_REGEX.findall(c_text))
                        except Exception:
                            pass
    except Exception:
        pass
        
    cleaned = clean_emails(found_emails)
    return ", ".join(cleaned) if cleaned else "Not Found"

def generate_variations(niche, location=""):
    """
    دنیا کے کسی بھی ملک، شہر اور کسی بھی نیش کے لیے ذہین کیوریز تیار کرنا۔
    اب اس میں کوئی ہارڈ کوڈڈ شہر یا ریئل اسٹیٹ کی پابندی نہیں ہے۔
    """
    niche = niche.strip()
    location = location.strip()
    
    queries = []
    if location:
        queries.extend([
            f"{niche} in {location}",
            f"best {niche} in {location}",
            f"{niche} services in {location}",
            f"top {niche} in {location}",
            f"{niche} near {location}"
        ])
    else:
        queries.extend([
            niche,
            f"best {niche}",
            f"top {niche}",
            f"{niche} services"
        ])
        
    # ڈپلیکیٹ کیوریز ہٹانا
    seen = set()
    unique_queries = []
    for q in queries:
        clean_q = " ".join(q.split())
        if clean_q not in seen:
            seen.add(clean_q)
            unique_queries.append(clean_q)
            
    return unique_queries

def load_seen_leads(file_path):
    """پہلے سے محفوظ شدہ لیڈز کو چیک کرنا تاکہ دوبارہ اسکریپ نہ ہوں (Deduplication)"""
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
                        seen.add(f"{b_name}::{phone}")
        except Exception as e:
            print(f"⚠️ پرانا ڈیٹا لوڈ کرنے میں تنبیہ: {e}")
    return seen

def save_lead(lead_data, master_file):
    """ہر لیڈ کو فوراً ماسٹر فائل میں محفوظ کرنا اور تمام نئے کالمز کو ایڈجسٹ کرنا"""
    df = pd.DataFrame([lead_data])
    file_exists = os.path.exists(master_file)
    
    if not file_exists:
        df.to_csv(master_file, index=False, header=True, encoding='utf-8-sig')
    else:
        try:
            existing_cols = pd.read_csv(master_file, nrows=0).columns.tolist()
            if 'Email / Gmail' not in existing_cols:
                # اگر پرانی فائل میں ای میل کا کالم نہیں تھا تو اسے اپ گریڈ کر کے ضم کرنا
                old_df = pd.read_csv(master_file)
                merged = pd.concat([old_df, df], ignore_index=True)
                merged.to_csv(master_file, index=False, encoding='utf-8-sig')
                return
        except Exception:
            pass
        df.to_csv(master_file, mode='a', index=False, header=False, encoding='utf-8-sig')

async def scrape_query(page, http_session, query, master_file, seen_leads, max_leads_per_query=40):
    url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}/"
    print(f"\n🔍 [شروع] تلاش جاری ہے: '{query}'")
    
    try:
        await page.goto(url, timeout=60000)
        
        # اگر گوگل کوکیز یا رضامندی کا پاپ اپ آئے تو قبول کرنا (یورپ/برطانیہ وغیرہ کے لیے)
        try:
            consent_btn = page.locator('button[aria-label*="Accept all"], button[aria-label*="Agree"], button:has-text("Accept all")')
            if await consent_btn.count() > 0:
                await consent_btn.first.click(timeout=3000)
                await page.wait_for_timeout(1000)
        except Exception:
            pass

        # لسٹنگز کا انتظار کرنا
        try:
            await page.wait_for_selector('a[href*="/maps/place/"]', timeout=15000)
        except Exception:
            print(f"⚠️ کوئی نتائج نہیں ملے یا وقت ختم ہو گیا برائے کیوری: {query}")
            return
            
        print("📜 نتائج لوڈ کرنے کے لیے آٹو سکرول جاری ہے...")
        feed_locator = page.locator('div[role="feed"]').first
        if await feed_locator.count() > 0:
            for _ in range(8):
                await feed_locator.evaluate("el => el.scrollBy(0, 10000)")
                await page.wait_for_timeout(1500)
        else:
            await page.hover('a[href*="/maps/place/"]')
            for _ in range(8):
                await page.mouse.wheel(0, 10000)
                await page.wait_for_timeout(1500)

        listings = await page.locator('a[href*="/maps/place/"]').all()
        print(f"📊 مجموعی طور پر {len(listings)} ممکنہ بزنسز دریافت ہوئے۔ تفصیلات نکالی جا رہی ہیں...")

        # لسٹنگز کے بنیادی لنکس اور نام جمع کرنا
        extracted_basic = []
        for l in listings[:max_leads_per_query]:
            name = await l.get_attribute('aria-label')
            link = await l.get_attribute('href')
            if name and link:
                clean_link = link.split('?')[0].split('/data=')[0].strip()
                if clean_link in seen_leads:
                    continue
                extracted_basic.append({'name': name.strip(), 'link': link.strip(), 'clean_link': clean_link})

        print(f"🎯 نئی منفرد لیڈز برائے پروسیسنگ: {len(extracted_basic)}")

        for info in extracted_basic:
            try:
                await page.goto(info['link'], timeout=30000)
                await page.wait_for_timeout(2000)
                
                # فون نمبر
                phone = "Not Found"
                phone_loc = page.locator('button[data-item-id*="phone"], [data-tooltip*="phone" i], button[aria-label*="Phone:"], button[aria-label*="فون:"]')
                if await phone_loc.count() > 0:
                    p_text = await phone_loc.first.get_attribute('aria-label')
                    if p_text:
                        phone = p_text.replace("Phone: ", "").replace("فون: ", "").strip()

                # ویب سائٹ
                website = "Not Found"
                web_loc = page.locator('a[data-item-id*="authority"], [data-tooltip*="website" i], a[aria-label*="Website:"], a[data-item-id="website"]')
                if await web_loc.count() > 0:
                    w_href = await web_loc.first.get_attribute('href')
                    if w_href:
                        website = w_href.strip()

                # ایڈریس / پتہ
                address = "Not Found"
                addr_loc = page.locator('button[data-item-id*="address"], [data-tooltip*="address" i], button[aria-label*="Address:"], button[aria-label*="پتہ:"]')
                if await addr_loc.count() > 0:
                    a_text = await addr_loc.first.get_attribute('aria-label')
                    if a_text:
                        address = a_text.replace("Address: ", "").replace("پتہ: ", "").strip()

                # کیٹگری / نیش
                category = "Not Found"
                cat_loc = page.locator('button[jsaction*="category"], div.fontBodyMedium button[jsaction*="category"]').first
                if await cat_loc.count() > 0:
                    category = (await cat_loc.inner_text()).strip()

                # ریٹنگ اور ریویوز
                rating = "Not Found"
                reviews_count = "0"
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

                # ویب سائٹ سے ای میل اور جی میل اسکریپ کرنا
                email = "Not Found"
                if website != "Not Found":
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

                email_display = f"📧 {email}" if email != "Not Found" else "📧 Not Found"
                phone_display = f"📞 {phone}" if phone != "Not Found" else "📞 Not Found"
                print(f"   ✔️ {info['name']} | {phone_display} | {email_display}")

            except Exception as e:
                # اگر کسی ایک لسٹنگ میں مسئلہ ہو تو آگے بڑھیں
                continue

    except Exception as e:
        print(f"❌ کیوری میں ایرر یا ٹائم آؤٹ: {query} ({e})")

async def main():
    print("=" * 60)
    print("   🌍 GLOBAL GOOGLE MAPS LEAD SCRAPER (PHONES + EMAILS)   ")
    print("=" * 60)
    
    user_input = input("\nنیش اور لوکیشن درج کریں (کوما سے الگ کریں، مثلاً:\n'Real Estate, Faisalabad' یا 'Dentist, London' یا 'Software Companies, Dubai'):\n> ")
    
    if not user_input.strip():
        print("❌ غلط ان پٹ! پروگرام بند ہو رہا ہے۔")
        return
        
    if "," in user_input:
        parts = user_input.split(",", 1)
        niche = parts[0].strip()
        location = parts[1].strip()
    elif " in " in user_input.lower():
        parts = user_input.lower().split(" in ", 1)
        niche = parts[0].strip()
        location = parts[1].strip()
    else:
        niche = user_input.strip()
        location = ""
        
    var_choice = input("\nکیا آپ اس کی خودکار سرچ کیوریز (Variations) چلانا چاہتے ہیں؟ (Y/N, Enter = Y): ").strip().lower()
    if var_choice in ['n', 'no']:
        queries = [f"{niche} {location}".strip()]
    else:
        queries = generate_variations(niche, location)
        
    print(f"\n🚀 کل {len(queries)} کیوریز تیار ہیں:")
    for idx, q in enumerate(queries, 1):
        print(f"   {idx}. {q}")
        
    master_file = "Master_Leads_Database.csv"
    seen_leads = load_seen_leads(master_file)
    print(f"📁 پہلے سے موجود لیڈز: {len(seen_leads)} (ڈپلیکیٹ لیڈز خودکار طور پر چھوڑ دی جائیں گی)")

    print("\n🌐 کرومیم براؤزر اور نیٹ ورک سیشن شروع ہو رہا ہے...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # ونڈوز براؤزر یوزر ایجنٹ سیٹ کرنا تاکہ بلاک نہ ہو
        await page.set_extra_http_headers({
            "Accept-Language": "en-US,en;q=0.9"
        })
        
        async with aiohttp.ClientSession() as http_session:
            for idx, q in enumerate(queries, 1):
                print(f"\n==================== کیوری {idx} / {len(queries)} ====================")
                await scrape_query(page, http_session, q, master_file, seen_leads)
                await asyncio.sleep(2)
                
        await browser.close()

    print("\n🎉 مبارک ہو! تمام لیڈز کا ڈیٹا (فون نمبرز، ای میلز/Gmails، ایڈریس، ویب سائٹ) کامیابی سے 'Master_Leads_Database.csv' میں محفوظ ہو چکا ہے!")

if __name__ == "__main__":
    asyncio.run(main())