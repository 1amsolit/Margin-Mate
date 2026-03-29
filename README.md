# Email Order Tracker

A local dashboard that connects to your Gmail via IMAP, automatically detects order emails from major Australian retailers, and tracks them from confirmation through to delivery.

## Features

- Automatically scans emails from **Target, Kmart, BigW, Amazon, Shopify**
- Detects order confirmed, shipped, and cancelled/refunded emails
- Extracts order numbers, item names, tracking numbers, and carrier links
- Inventory management — track stock, record sales, calculate revenue & profit
- Dark UI inspired by Parcel

## Setup

### 1. Requirements

- Python 3.10+
- Gmail account with IMAP enabled

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure

Copy the example config and fill in your details:

```bash
cp config.example.json config.json
```

Edit `config.json` with your Gmail address and an [app password](https://myaccount.google.com/apppasswords).

> **Note:** You must enable 2-factor authentication on your Google account before you can generate an app password.

### 4. Run

```bash
python app.py
```

Or on Windows, double-click `start.bat`.

Open [http://localhost:5000](http://localhost:5000) in your browser.

## Config

| Field | Description |
|-------|-------------|
| `imap.username` | Your Gmail address |
| `imap.password` | Gmail app password (not your account password) |
| `imap.scan_days_back` | How many days of emails to scan on first run |
| `imap.check_interval_seconds` | How often to auto-check emails (default: 300s) |

## Supported Carriers

Australia Post, StarTrack, GoPeople, Couriers Please, DHL, FedEx, UPS, Amazon Logistics, Sendle, Aramex/Fastway, TNT, Toll, Hunter Express

## Notes

- `config.json` and `orders.db` are gitignored — your credentials and order data stay local
- Emails are never stored, only the extracted order data
