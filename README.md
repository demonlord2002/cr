# 🍥 Crunchyroll Downloader Bot

A Telegram bot that can download episodes from Crunchyroll and send them directly to your chat.

## 🚀 Features
- Download videos from Crunchyroll (supports premium login if credentials are provided)
- Send directly to Telegram
- Easy Heroku deployment

---

## 🛠 Deployment

### 🔹 Deploy to Heroku
Click the button below to deploy to Heroku:

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/demonlord2002/cr)

---

## ⚙ Configuration
Create a `.env` file (or set Heroku config vars) with:

```env
BOT_TOKEN=your_telegram_bot_token
API_ID=your_telegram_api_id
API_HASH=your_telegram_api_hash
CR_EMAIL=your_crunchyroll_email
CR_PASSWORD=your_crunchyroll_password
OWNER_ID=your_telegram_id
