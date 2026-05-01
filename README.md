# 🎉 GW Bot — Telegram Giveaway Bot

## Setup

1. **Get a bot token** from [@BotFather](https://t.me/BotFather) → `/newbot`
2. **Get your Telegram user ID** from [@userinfobot](https://t.me/userinfobot)
3. Edit `.env`:
```
BOT_TOKEN=your_token_here
OWNER_ID=your_numeric_id
```
4. Install dependencies:
```
pip install -r requirements.txt
```
5. Run:
```
python bot.py
```

---

## Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/start` | Anyone | Shows active giveaways or processes entry deep-link |
| `/admin` | Owner + Admins | Opens admin panel |
| `/cancel` | Anyone | Cancels current conversation |

---

## Admin Panel Features

- **Create Active GW** — Channel-based: participants must join channel, top 10% texters in discussion group are winner pool
- **Create Normal GW** — Anyone can enter via link
- **Add/Remove Admins** — Owner only, by Telegram numeric ID
- **List Admins** — View all current admins
- **List Running GWs** — See all live giveaways with entry counts

---

## How Giveaways Work

### Active GW (Channel-based)
1. Admin sets: channel @username, discussion link, prize, description, duration
2. Bot posts to specified channel with a **Participate!** button
3. Users click → bot DMs them → checks they joined the channel → sends **math captcha image**
4. On correct answer → entry confirmed
5. Bot tracks messages in discussion group
6. On expiry → selects top 10% texters who entered → picks one random winner

### Normal GW
1. Admin sets: prize, description, duration
2. Same captcha flow — no channel join required
3. On expiry → picks one random winner from all entries

---

## Anti-Fake System
- Each user can only enter once per giveaway (enforced by DB unique constraint)  
- Captcha (math image) blocks automated entries — 3 attempts max  
- Channel membership verified via Telegram API (active GW)  
- Captcha sessions expire after 5 minutes  

---

## Entry Count Updates
The post is automatically edited **every 60 seconds** with the latest entry count.

---

## File Structure
```
Gwbot/
├── bot.py           # Main entry point
├── database.py      # SQLite async layer (aiosqlite)
├── captcha.py       # Custom math captcha image generator (Pillow)
├── formatter.py     # Post text builder
├── handlers/
│   ├── admin.py     # Admin panel conversation handler
│   ├── user.py      # /start deep-link + captcha flow
│   └── jobs.py      # Scheduled jobs (update posts, end giveaways, count messages)
├── requirements.txt
└── .env
```
