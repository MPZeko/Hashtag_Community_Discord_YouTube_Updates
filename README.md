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
- The script calls YouTube Data API and uses built-in channel IDs by default (with optional secret-based overrides).
- It compares latest video IDs against `.github/data/last_seen.json` to avoid duplicate Discord posts.
- If there are new videos, it posts them to Discord in chronological order.

> On first run, state is initialized and historical videos are not posted by default.

## Discord preview behavior

Messages include the direct YouTube URL (`https://www.youtube.com/watch?v=...`). Discord normally auto-embeds this as a video preview; if not, clicking opens YouTube.

## Required GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

- `DISCORD_WEBHOOK_URL`
- `YOUTUBE_API_KEY` **or** `Youtube_Hashtag_United_API` (this matches the exact secret you created)
- `HASHTAG_UNITED_CHANNEL_ID` (optional override; default is already configured)
- `HASHTAG_UNITED_EXTRA_CHANNEL_ID` (optional override; default is already configured)

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

- `run_mode`:
  - `sync`: normal YouTube-to-Discord sync
  - `webhook_test`: sends a standalone test message to Discord (does not call YouTube API)
- `channel`: `all`, `hashtag_united`, or `hashtag_united_extra` (sync mode)
- `force_latest`:
  - `false`: only genuinely new uploads
  - `true`: always post current latest upload (manual verification)
- `webhook_test_message`: optional text used in webhook test mode

## Files

- `.github/workflows/youtube-discord-updates.yml`: workflow
- `.github/scripts/youtube_to_discord.py`: main sync script
- `.github/data/last_seen.json`: state storage


## Built-in default channel IDs

- Hashtag United: `UCeJ73ymlLhLctITwdi9iCVw`
- Hashtag United Extra: `UCno_OxtA1RcOfWjWjUPpfQg`

You can still override them using the optional channel ID secrets above.


## Troubleshooting 403 errors

- Webhook requests are sent as JSON with `Content-Type: application/json`, `Accept: application/json`, and a standard browser-like `User-Agent` for maximum compatibility.
If the workflow logs show `HTTP Error 403: Forbidden` or `YouTube API 403 (...)`, the most common cause is API key restrictions.

Check the Google Cloud API key settings:

- Ensure **YouTube Data API v3** is enabled on the same project as the key.
- If key restrictions are enabled, prefer **no application restriction** for GitHub-hosted runners (their IPs are dynamic).
- If you use API restrictions, include **YouTube Data API v3**.
- Verify the secret value is the raw API key string (no quotes/spaces).

The script now prints the exact YouTube API error reason in logs to help diagnose this.

- If error mentions `Discord webhook HTTP 401/403/404`, the webhook URL/permissions are invalid; recreate webhook in the target Discord channel and update `DISCORD_WEBHOOK_URL`.

- If error contains `error code: 1010`, the webhook request is being blocked upstream; regenerate the webhook, verify the exact URL in `DISCORD_WEBHOOK_URL`, and retry with `run_mode=webhook_test` to isolate Discord from YouTube.
