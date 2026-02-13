# Hashtag Community Discord YouTube Updates

This repository contains an automated GitHub Actions workflow that watches selected YouTube channels and posts new uploads to Discord through a webhook.

## Channels monitored

- `https://www.youtube.com/@HashtagUnited`
- `https://www.youtube.com/@HashtagUnitedExtra`

## Why previous versions failed

Direct polling of YouTube pages/feeds from GitHub-hosted runners can return intermittent or persistent **HTTP 403/404** responses.

To make the automation stable, this implementation uses the **official YouTube Data API** (`googleapis.com`) instead of scraping/polling `youtube.com` feed endpoints.

## How it works

- A scheduled GitHub Actions workflow runs every 2 hours.
- The script calls YouTube Data API and resolves each channel ID from the configured handle automatically (or uses optional channel ID overrides if provided).
- It compares latest video IDs against `.github/data/last_seen.json` to avoid duplicate Discord posts.
- If there are new videos, it posts them to Discord in chronological order.

> On first run, state is initialized and historical videos are not posted by default.

## Discord preview behavior

Messages include the direct YouTube URL (`https://www.youtube.com/watch?v=...`). Discord normally auto-embeds this as a video preview; if not, clicking opens YouTube.

## Required GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

- `DISCORD_WEBHOOK_URL`
- `YOUTUBE_API_KEY` **or** `Youtube_Hashtag_United_API` (this matches the exact secret you created)
- `HASHTAG_UNITED_CHANNEL_ID` (optional override)
- `HASHTAG_UNITED_EXTRA_CHANNEL_ID` (optional override)

## How to get `YOUTUBE_API_KEY`

1. Open Google Cloud Console.
2. Create/select a project.
3. Enable **YouTube Data API v3**.
4. Create an API key.
5. Save it as `YOUTUBE_API_KEY` secret.

## How to get channel IDs

Use either method:

- From channel page source tools/extensions that show `channelId` (`UC...`), or
- Via YouTube Data API explorer / script once.

Then store:

- `HASHTAG_UNITED_CHANNEL_ID` = channel ID for `@HashtagUnited`
- `HASHTAG_UNITED_EXTRA_CHANNEL_ID` = channel ID for `@HashtagUnitedExtra`

## Manual testing (Run workflow)

In **Actions → YouTube to Discord Updates → Run workflow**, choose:

- `channel`: `all`, `hashtag_united`, or `hashtag_united_extra`
- `force_latest`:
  - `false`: only genuinely new uploads
  - `true`: always post current latest upload (manual verification)

## Files

- `.github/workflows/youtube-discord-updates.yml`: workflow
- `.github/scripts/youtube_to_discord.py`: main sync script
- `.github/data/last_seen.json`: state storage
