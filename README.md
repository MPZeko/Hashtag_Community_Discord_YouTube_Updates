# Hashtag Community Discord YouTube Updates

This repository contains an automated GitHub Actions workflow that watches selected YouTube channels and posts new uploads to Discord through a webhook.

## Channels monitored

- `https://www.youtube.com/@HashtagUnited`
- `https://www.youtube.com/@HashtagUnitedExtra`

## How it works

- A scheduled GitHub Actions workflow runs every 2 hours.
- It reads each channel's YouTube Atom feed directly via stable feed endpoints.
- This avoids fragile channel-page scraping that can fail with HTTP 403 in CI.
- It compares the latest videos against a state file (`.github/data/last_seen.json`) to avoid duplicate Discord posts.
- If there are new videos, it posts them to Discord in chronological order.

> On the very first run, the workflow initializes state and does not post historical videos by default.

## Discord preview behavior

Messages include the direct YouTube video URL. Discord usually auto-embeds YouTube links so the video can be previewed in Discord. If embedding is unavailable, users can still click through to YouTube.

## Setup

1. Go to your GitHub repository settings.
2. Open **Settings → Secrets and variables → Actions**.
3. Add a new repository secret named:
   - `DISCORD_WEBHOOK_URL`
4. Set its value to your Discord channel webhook URL.

## Manual testing (Run workflow)

The workflow supports manual execution from **Actions → YouTube to Discord Updates → Run workflow**.

You can choose:

- `channel`
  - `all`
  - `hashtag_united`
  - `hashtag_united_extra`
- `force_latest`
  - `false`: normal mode (only genuinely new uploads)
  - `true`: always send the current latest upload (useful for manual verification)

## Files

- `.github/workflows/youtube-discord-updates.yml`: workflow definition
- `.github/scripts/youtube_to_discord.py`: sync script with comments
- `.github/data/last_seen.json`: persistent last-posted state per channel
