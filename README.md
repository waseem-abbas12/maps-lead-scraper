# 🌍 Global Google Maps Lead Scraper Web Portal

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/waseem-abbas12/maps-lead-scraper)

A powerful, password-protected Google Maps lead scraping dashboard capable of extracting business information worldwide with dual extraction for **Phone Numbers and Emails / Gmails**.

## Features
- **Access Controlled:** Login gate with session security.
- **Dual Contact Extraction:** Phone numbers + Emails and Gmails extracted directly from official business websites.
- **Worldwide Support:** Any city, any country, and any niche.
- **Live Terminal Stream:** Real-time extraction logs and live metrics.
- **Master Database & Deduplication:** Automatic duplicate skipping and 1-click CSV download.
- **Docker & Cloud Ready:** Runs indefinitely without serverless timeouts.

## Quick Start (Local)
`ash
pip install -r requirements.txt
playwright install --with-deps chromium
python app.py
`
Open **http://localhost:8000**
- Username: dmin
- Password: leads@secret2026

## Deploy to Cloud (Render)
Click the **Deploy to Render** button above or import repository waseem-abbas12/maps-lead-scraper into Render.com as a Web Service.
