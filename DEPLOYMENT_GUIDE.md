# 🚀 Lead Scraper Web Portal - Deployment & Usage Guide

## 1. Local Machine Par Chalane Ka Tareeqa (Instant Run)

Apne computer par web dashboard chalane ke liye:
```bash
python app.py
```
Phir browser me ye link kholein:
👉 **http://localhost:8000**

### Login Credentials (Default):
* **Username:** `admin`
* **Password:** `leads@secret2026`

*(Aap `.env` file me ja kar username aur password apni marzi ka rakh sakte hain)*

---

## 2. Render.com Par Free Deploy Karne Ka Tareeqa (Cloud 24/7)

Render.com par ye Docker ke zariye baghair kisi timeout ya browser crash ke bilkul free chalta hai:

### Step 1: Code GitHub par upload karein
1. [GitHub.com](https://github.com) par ek new private repository banayein (e.g. `lead-scraper-web`).
2. Is folder me terminal khol kar ye commands chalayein:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin YOUR_GITHUB_REPO_URL
   git push -u origin main
   ```

### Step 2: Render.com par 1-Click Setup
1. [Render.com](https://render.com) par free account banayein ya login karein.
2. **New +** button par click kar ke **Web Service** select karein.
3. Apni GitHub repository select karein.
4. **Environment:** `Docker` select karein (Render khud `Dockerfile` detect kar lega).
5. **Environment Variables** me ye add karein:
   * `ADMIN_USERNAME` = Aapka username (e.g. `admin`)
   * `ADMIN_PASSWORD` = Aapka secret password jise sirf aap jante hon
   * `PORT` = `8000`
6. **Create Web Service** par click karein.

Render khud Chromium install kar ke aapko ek live URL de dega (e.g. `https://my-lead-scraper.onrender.com`).
Sirf wahi log use kar sakenge jinhe aap username aur password denge!

---

## 3. VPS ya Kisi Bhi Server Par Docker se Chalana

Agar aapke paas DigitalOcean, Hetzner, AWS ya koi bhi Ubuntu server hai:
```bash
docker build -t lead-scraper .
docker run -d -p 8000:8000 --env-file .env lead-scraper
```
