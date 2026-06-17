# Manga Delivery Telegram Bot

A Telegram bot built with Pyrogram that fetches manga from MangaDex, compiles chapters into PDFs, stores them in a private Telegram channel, and delivers them to users.

## Features
- Search manga by title using fuzzy matching.
- Browse manga by genre.
- View latest additions and random manga.
- Automated background scraper pulling from MangaDex API.
- Generates PDFs from downloaded chapter pages.

## Setup Instructions

### 1. Telegram API Credentials
1. Go to [BotFather](https://t.me/botfather) to create a new bot and get the `BOT_TOKEN`.
2. Go to [my.telegram.org](https://my.telegram.org), log in, and navigate to "API development tools" to get your `API_ID` and `API_HASH`.
3. Get your Telegram User ID (you can use bots like `@userinfobot` to find this). This is required for the `/stats` command.

### 2. Storage Channel Setup
1. Create a new Private Channel on Telegram.
2. Add your newly created bot to the channel as an Administrator (needs permission to post messages).
3. Find the Channel ID. You can forward a message from the channel to `@userinfobot` or use clients that show IDs. The ID should start with `-100`.

### 3. MongoDB Setup
1. Create a free cluster on [MongoDB Atlas](https://www.mongodb.com/cloud/atlas).
2. Set up a database user and allow access from anywhere (`0.0.0.0/0`).
3. Get the connection string (`DB_URL`).

### 4. Local Deployment
1. Clone this repository.
2. Copy `.env.example` to `.env` and fill in all the required values.
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the bot:
   ```bash
   python main.py
   ```

### 5. Render Deployment
This repository is configured for easy deployment on [Render](https://render.com).
1. Connect your repository to Render.
2. A Web Service will be created automatically via the `render.yaml` configuration.
3. You MUST fill out the Environment Variables in the Render dashboard based on your credentials.
4. Set up an external ping service like [cron-job.org](https://cron-job.org/) to hit your `https://your-app.onrender.com/health` endpoint every 10 minutes to prevent the free tier from sleeping, ensuring the scraper runs consistently.
