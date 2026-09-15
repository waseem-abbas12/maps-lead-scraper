# 🚀 Lead Scraper Web Portal - Free Deployment Guide (No Credit Card)

> **Important Note:** **Neon.tech** sirf ek database (PostgreSQL) service hai, wahan web applications ya browser automation (Playwright/Chrome) host nahi hotay. 
> Lead Scraper ko chalane ke liye ek aisi hosting chahiye jahan **Docker + Chromium Browser** chal sakay aur **Credit Card na mangay**.

---

## 🌟 Option 1: Hugging Face Spaces (100% FREE - No Card Required) - SABSE BEST!

Hugging Face Spaces par **kisi credit card ki zaroorat nahi hoti**, aur ye free tier me **16 GB RAM + 2 vCPU** deta hai (Render se 32 guna zyada RAM, taake Chromium kabhie crash na ho).

### Step-by-Step Tareeqa:

1. **Account Banayein:**
   * [huggingface.co](https://huggingface.co) par jayein aur free account banayein (sirf Email ya GitHub se).

2. **New Space Create Karein:**
   * Upar profile icon par click kar ke **New Space** par click karein.
   * **Space Name:** e.g. `google-maps-lead-scraper`
   * **License:** `mit` ya `apache-2.0`
   * **Space SDK:** **Docker** select karein (Blank).
   * **Space Hardware:** `CPU basic • 2 vCPU • 16GB RAM • Free` (default selected hota hai).
   * **Visibility:** `Public` ya `Private` (agar private karenge toh sirf aap hi open kar sakenge).
   * **Create Space** button par click karein.

3. **Code Upload Karein:**
   * Space create hote hi aapko Git clone / push command milegi.
   * Apne is project folder me terminal khol kar ye commands chalayein:
   ```bash
   git remote add space https://huggingface.co/spaces/YOUR_USERNAME/YOUR_SPACE_NAME
   git push space main
   ```
   *(Ya aap Hugging Face Space ke "Files" tab me ja kar directly files drag-and-drop / upload bhi kar sakte hain)*

4. **Variables Set Karein (Secrets):**
   * Space ke **Settings** tab me jayein -> **Variables and secrets**.
   * **New secret** par click karein:
     * `ADMIN_USERNAME` = `admin`
     * `ADMIN_PASSWORD` = Aapka secret password

5. **Done!**
   * Hugging Face automatically Docker container build karega aur aapko ek live URL mil jayega:
   * 👉 `https://YOUR_USERNAME-YOUR_SPACE_NAME.hf.space`

---

## ⚡ Option 2: Cloudflare Tunnel (Apne PC Se Live URL - 100% Free & Fast)

Agar aap kisi cloud service ke chakkar me nahi parna chahte aur chahte hain ke scraper aapke apne computer ke fast internet aur processor par chalay, lekin browser link kahin bhi dunya me khul sakay (bina kisi port forwarding ya card ke):

1. Apne PC par terminal me app chalayein:
   ```bash
   python app.py
   ```
2. Ek doosra terminal khol kar Cloudflare Tunnel chalayein:
   ```bash
   winget install --id Cloudflare.cloudflared
   cloudflared tunnel --url http://localhost:8000
   ```
3. Cloudflare aapko ek secure HTTPS link de dega (e.g. `https://random-words.trycloudflare.com`).
4. Ye link aap mobile ya kisi bhi computer se open kar ke leads nikaal sakte hain!

---

## 3. Login Credentials (Default)

* **Username:** `admin`
* **Password:** `leads@secret2026`
*(Aap `.env` ya Cloud Environment Variables me apni marzi ka password rakh sakte hain)*
