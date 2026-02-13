#!/usr/bin/env python3
"""Post new videos from selected YouTube channels to Discord via webhook.

This script is intended to run in GitHub Actions, but it can also be run locally.
It keeps a small JSON state file with the last posted video ID per channel.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


CHANNELS = {
    "hashtag_united": {
        "label": "Hashtag United",
        "channel_url": "https://www.youtube.com/@HashtagUnited",
        # We intentionally use RSS feed URLs directly to avoid scraping channel HTML,
        # because that can return 403 in GitHub-hosted environments.
        "feed_urls": [
            # Keep user feed as one possible source.
            "https://www.youtube.com/feeds/videos.xml?user=HashtagUnited",
        ],
    },
    "hashtag_united_extra": {
        "label": "Hashtag United Extra",
        "channel_url": "https://www.youtube.com/@HashtagUnitedExtra",
        "feed_urls": [
            "https://www.youtube.com/feeds/videos.xml?user=HashtagUnitedExtra",
        ],
    },
}


@dataclass
class Video:
    video_id: str
    title: str
    url: str
    published: str


def _http_get_text(url: str) -> str:
    """Fetch text from URL with a browser-like User-Agent for compatibility."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_feed(xml_text: str) -> List[Video]:
    """Parse a YouTube Atom feed payload into video records."""
    root = ET.fromstring(xml_text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "yt": "http://www.youtube.com/xml/schemas/2015",
    }

    videos: List[Video] = []
    for entry in root.findall("atom:entry", ns):
        video_id = entry.findtext("yt:videoId", default="", namespaces=ns)
        title = entry.findtext("atom:title", default="", namespaces=ns)
        published = entry.findtext("atom:published", default="", namespaces=ns)
        link_el = entry.find("atom:link", ns)
        url = link_el.attrib.get("href", "") if link_el is not None else ""

        if video_id and url:
            videos.append(Video(video_id=video_id, title=title, url=url, published=published))

    return videos


def fetch_feed_videos(feed_urls: List[str]) -> List[Video]:
    """Try feed URLs in order and return videos from the first successful source."""
    last_error: str | None = None

    for feed_url in feed_urls:
        try:
            xml_text = _http_get_text(feed_url)
            videos = parse_feed(xml_text)
            if videos:
                return videos
            last_error = f"No entries in feed: {feed_url}"
        except (urllib.error.URLError, ET.ParseError) as exc:
            last_error = f"{feed_url} -> {exc}"
            continue

    raise RuntimeError(last_error or "No valid feed source available")




def resolve_channel_id_with_ytdlp(channel_url: str) -> str | None:
    """Resolve YouTube channel_id using yt-dlp as a robust fallback.

    This avoids relying on brittle HTML parsing and works when direct user-feed URLs
    are unknown or return 404.
    """
    if not shutil.which("yt-dlp"):
        return None

    # We only need metadata, so we request a tiny flat playlist payload.
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--playlist-end",
        "1",
        "-J",
        f"{channel_url}/videos",
    ]

    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
        data = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return None

    for key in ("channel_id", "uploader_id"):
        value = data.get(key)
        if isinstance(value, str) and value.startswith("UC"):
            return value

    return None


def fetch_videos_with_fallback(cfg: Dict[str, object]) -> List[Video]:
    """Fetch videos from configured feeds, then fallback to channel-id resolution."""
    feed_urls = cfg.get("feed_urls", [])
    if isinstance(feed_urls, list) and feed_urls:
        try:
            return fetch_feed_videos(feed_urls)
        except RuntimeError:
            pass

    # Fallback: resolve channel ID via yt-dlp and query official feed endpoint.
    channel_url = str(cfg.get("channel_url", "")).rstrip("/")
    channel_id = resolve_channel_id_with_ytdlp(channel_url)
    if channel_id:
        return fetch_feed_videos([f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"])

    raise RuntimeError("Could not fetch feed from configured URLs and yt-dlp fallback did not resolve channel ID")


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
    """Return videos to post.

    - force_latest: post the latest video even if it has been seen.
    - normal mode: post all videos that are newer than last seen ID.
    """
    if not videos:
        return []

    if force_latest:
        return [videos[0]]

    if not last_seen_video_id:
        # First run bootstrap: avoid posting historical content by default.
        return []

    if videos[0].video_id == last_seen_video_id:
        return []

    new_videos: List[Video] = []
    for video in videos:
        if video.video_id == last_seen_video_id:
            break
        new_videos.append(video)

    # Post from oldest -> newest for natural order in Discord.
    return list(reversed(new_videos))


def post_to_discord(webhook_url: str, channel_label: str, video: Video) -> None:
    """Post one video message to Discord webhook.

    We include the plain URL in content, so Discord can auto-expand rich embeds.
    """
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
        ),
    }

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status >= 300:
            raise RuntimeError(f"Discord webhook failed with status {resp.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post new YouTube uploads to Discord")
    parser.add_argument(
        "--channel",
        choices=["all", *CHANNELS.keys()],
        default="all",
        help="Channel key to process (default: all)",
    )
    parser.add_argument(
        "--state-file",
        default=".github/data/last_seen.json",
        help="Path to JSON file storing the last posted video IDs",
    )
    parser.add_argument(
        "--force-latest",
        action="store_true",
        help="Always post the latest video for selected channels",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook_url:
        print("ERROR: DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 2

    state_file = Path(args.state_file)
    state = load_state(state_file)

    selected_keys = list(CHANNELS.keys()) if args.channel == "all" else [args.channel]
    state_changed = False
    posted_count = 0

    for channel_key in selected_keys:
        cfg = CHANNELS[channel_key]
        print(f"Processing {channel_key} ({cfg['channel_url']})")

        try:
            videos = fetch_videos_with_fallback(cfg)
            if not videos:
                print(f"  No feed entries found for {channel_key}")
                continue

            last_seen = state.get(channel_key)
            videos_to_post = should_post_videos(videos, last_seen, args.force_latest)

            if not last_seen:
                # Bootstrap state on first run so the next run posts only genuinely new videos.
                state[channel_key] = videos[0].video_id
                state_changed = True
                print(f"  Initialized last-seen to {videos[0].video_id}")

            for video in videos_to_post:
                post_to_discord(webhook_url, cfg["label"], video)
                posted_count += 1
                print(f"  Posted: {video.video_id} - {video.title}")

            # Update state to current latest once processing succeeds.
            if state.get(channel_key) != videos[0].video_id:
                state[channel_key] = videos[0].video_id
                state_changed = True
                print(f"  Updated last-seen to {videos[0].video_id}")

        except (RuntimeError, urllib.error.URLError, ET.ParseError, TimeoutError) as exc:
            print(f"  ERROR for {channel_key}: {exc}", file=sys.stderr)
            return 1

    if state_changed:
        save_state(state_file, state)

    print(f"Done. Posted {posted_count} video(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
