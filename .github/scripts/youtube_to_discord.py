#!/usr/bin/env python3
"""Post new videos from selected YouTube channels to Discord via webhook.

This version uses the official YouTube Data API (googleapis.com) instead of
scraping/feed polling from youtube.com endpoints, which can return 403 in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


CHANNELS = {
    "hashtag_united": {
        "label": "Hashtag United",
        "handle": "HashtagUnited",
        # Default channel ID provided by repository owner.
        "default_channel_id": "UCeJ73ymlLhLctITwdi9iCVw",
        # Optional override via secret/env.
        "channel_id_env": "HASHTAG_UNITED_CHANNEL_ID",
    },
    "hashtag_united_extra": {
        "label": "Hashtag United Extra",
        "handle": "HashtagUnitedExtra",
        # Default channel ID provided by repository owner.
        "default_channel_id": "UCno_OxtA1RcOfWjWjUPpfQg",
        # Optional override via secret/env.
        "channel_id_env": "HASHTAG_UNITED_EXTRA_CHANNEL_ID",
    },
}



@dataclass
class Video:
    video_id: str
    title: str
    url: str
    published: str


def _format_youtube_api_error(err: urllib.error.HTTPError) -> str:
    """Extract human-friendly reason from YouTube API error responses."""
    try:
        raw = err.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        error_obj = payload.get("error", {}) if isinstance(payload, dict) else {}

        message = error_obj.get("message") if isinstance(error_obj, dict) else None
        details = error_obj.get("errors", []) if isinstance(error_obj, dict) else []
        reason = None
        if isinstance(details, list) and details:
            first = details[0]
            if isinstance(first, dict):
                reason = first.get("reason")

        if reason and message:
            return f"YouTube API {err.code} ({reason}): {message}"
        if message:
            return f"YouTube API {err.code}: {message}"
    except Exception:
        pass

    return f"HTTP Error {err.code}: {err.reason}"


def _http_get_json(url: str) -> Dict:
    """Fetch JSON from a URL and parse it with clearer HTTP diagnostics."""
    req = urllib.request.Request(url, headers={"User-Agent": "youtube-discord-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        raise RuntimeError(_format_youtube_api_error(err)) from err
    except urllib.error.URLError as err:
        raise RuntimeError(f"Network error: {err}") from err




def resolve_channel_id_from_handle(api_key: str, handle: str) -> str | None:
    """Resolve channel ID via official YouTube Data API using channel handle."""
    params = {
        "part": "id",
        "forHandle": handle,
        "key": api_key,
    }
    url = "https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode(params)

    try:
        payload = _http_get_json(url)
    except Exception:
        return None

    items = payload.get("items", [])
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            cid = first.get("id")
            if isinstance(cid, str) and cid.startswith("UC"):
                return cid

    return None


def fetch_latest_videos_from_api(api_key: str, channel_id: str, max_results: int = 10) -> List[Video]:
    """Fetch latest channel videos via YouTube Data API search endpoint."""
    params = {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "type": "video",
        "maxResults": str(max_results),
        "key": api_key,
    }
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
    payload = _http_get_json(url)

    items = payload.get("items", [])
    videos: List[Video] = []
    for item in items:
        if not isinstance(item, dict):
            continue

        id_obj = item.get("id", {})
        snippet = item.get("snippet", {})
        video_id = id_obj.get("videoId") if isinstance(id_obj, dict) else None
        title = snippet.get("title", "") if isinstance(snippet, dict) else ""
        published = snippet.get("publishedAt", "") if isinstance(snippet, dict) else ""

        if not video_id:
            continue

        videos.append(
            Video(
                video_id=video_id,
                title=title,
                published=published,
                url=f"https://www.youtube.com/watch?v={video_id}",
            )
        )

    return videos


def load_state(path: Path) -> Dict[str, str]:
    """Load last-seen map from JSON; return empty map when missing."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: Dict[str, str]) -> None:
    """Persist state in stable JSON format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def should_post_videos(videos: List[Video], last_seen_video_id: str | None, force_latest: bool) -> List[Video]:
    """Return videos to post based on state and mode."""
    if not videos:
        return []

    if force_latest:
        return [videos[0]]

    if not last_seen_video_id:
        # First run bootstrap: avoid posting all historical uploads.
        return []

    if videos[0].video_id == last_seen_video_id:
        return []

    new_videos: List[Video] = []
    for video in videos:
        if video.video_id == last_seen_video_id:
            break
        new_videos.append(video)

    # Send in chronological order for cleaner Discord timeline.
    return list(reversed(new_videos))


def post_to_discord(webhook_url: str, channel_label: str, video: Video) -> None:
    """Post one video to Discord webhook. URL is included for Discord embed preview."""
    published_display = video.published
    try:
        dt = datetime.fromisoformat(video.published.replace("Z", "+00:00")).astimezone(timezone.utc)
        published_display = dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        pass

    payload = {
        "content": (
            f"📺 **{channel_label}** uploaded a new video\n"
            f"**{video.title}**\n"
            f"Published: {published_display}\n"
            f"{video.url}"
        )
    }

    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord webhook failed with status {resp.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post new YouTube uploads to Discord")
    parser.add_argument("--channel", choices=["all", *CHANNELS.keys()], default="all")
    parser.add_argument("--state-file", default=".github/data/last_seen.json")
    parser.add_argument("--force-latest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 2

    youtube_api_key = (
        os.environ.get("YOUTUBE_API_KEY", "").strip()
        or os.environ.get("Youtube_Hashtag_United_API", "").strip()
    )
    if not youtube_api_key:
        print("ERROR: YOUTUBE_API_KEY is not set (or Youtube_Hashtag_United_API)", file=sys.stderr)
        return 2

    state_file = Path(args.state_file)
    state = load_state(state_file)

    selected_keys = list(CHANNELS.keys()) if args.channel == "all" else [args.channel]
    state_changed = False
    posted_count = 0
    channel_errors: List[str] = []

    for channel_key in selected_keys:
        cfg = CHANNELS[channel_key]
        env_name = cfg["channel_id_env"]
        channel_id = os.environ.get(env_name, "").strip()
        source = f"env ${env_name}"

        # Use built-in stable defaults when no env override is configured.
        if not channel_id:
            channel_id = str(cfg.get("default_channel_id", "")).strip()
            source = "repository default"

        # As a final fallback, attempt handle-based API lookup.
        if not channel_id:
            resolved = resolve_channel_id_from_handle(youtube_api_key, str(cfg["handle"]))
            if resolved:
                channel_id = resolved
                source = f"handle @{cfg['handle']}"

        print(f"Processing {channel_key} (channel_id from {source})")

        if not channel_id:
            channel_errors.append(f"ERROR for {channel_key}: could not resolve channel id")
            print(f"  ERROR for {channel_key}: could not resolve channel id", file=sys.stderr)
            continue

        try:
            videos = fetch_latest_videos_from_api(youtube_api_key, channel_id)
            if not videos:
                print(f"  No videos returned for {channel_key}")
                continue

            last_seen = state.get(channel_key)
            videos_to_post = should_post_videos(videos, last_seen, args.force_latest)

            if not last_seen:
                state[channel_key] = videos[0].video_id
                state_changed = True
                print(f"  Initialized last-seen to {videos[0].video_id}")

            for video in videos_to_post:
                post_to_discord(webhook_url, cfg["label"], video)
                posted_count += 1
                print(f"  Posted: {video.video_id} - {video.title}")

            if state.get(channel_key) != videos[0].video_id:
                state[channel_key] = videos[0].video_id
                state_changed = True
                print(f"  Updated last-seen to {videos[0].video_id}")

        except Exception as exc:
            channel_errors.append(f"ERROR for {channel_key}: {exc}")
            print(f"  ERROR for {channel_key}: {exc}", file=sys.stderr)

    if state_changed:
        save_state(state_file, state)

    if channel_errors and posted_count == 0:
        print("Failed to process all selected channels.", file=sys.stderr)
        return 1

    if channel_errors:
        print(f"Completed with warnings. Posted {posted_count} video(s).")
        return 0

    print(f"Done. Posted {posted_count} video(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
