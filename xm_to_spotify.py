#!/usr/bin/env python3
"""
xm_to_spotify_connector.py
Accumulates tracks from XMPlaylists (station=1stwave) into Spotify playlists
named "SiriusXM 1st Wave Archive — Vol. N", auto-creating new volumes when the
current volume approaches Spotify's 10,000-track limit.
"""

import os
import time
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------- CONFIG ----------------
XM_CHANNEL = "1stwave"
PLAYLIST_PREFIX = "SiriusXM 1st Wave Archive"
PLAYLIST_MAX = 10000
PLAYLIST_THRESHOLD = 9900

# Local metadata/caches
META_FILE = "meta.json"
SEEN_FILE = "seen.json"

# Spotify env vars
SP_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID")
SP_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET")
SP_REFRESH_TOKEN = os.environ.get("SPOTIFY_REFRESH_TOKEN")
SP_USER_ID = os.environ.get("SPOTIFY_USER_ID")

if not all([SP_CLIENT_ID, SP_CLIENT_SECRET, SP_REFRESH_TOKEN, SP_USER_ID]):
    logging.error("Missing one or more required Spotify environment variables.")
    raise SystemExit(1)

# ---------------- Helpers ----------------

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# ---------------- API TOOL ----------------

def get_access_token():
    """Refresh Spotify access token using the connector."""
    tokens = api_tool.call(
        "spotify_web_api.refresh_access_token",
        {
            "client_id": SP_CLIENT_ID,
            "client_secret": SP_CLIENT_SECRET,
            "refresh_token": SP_REFRESH_TOKEN
        }
    )
    return tokens["access_token"]

def fetch_xm_tracks():
    """Get latest tracks from XMPlaylists via connector."""
    try:
        data = api_tool.call(
            "xm_playlists.get_recent_tracks",
            {"channel": XM_CHANNEL}
        )
    except Exception as e:
        logging.error("Failed to fetch XMPlaylists data: %s", e)
        return []

    results = []
    for item in data.get("tracks", []):
        title = (item.get("song") or "").strip()
        artist = (item.get("artist") or "").strip()
        if title and artist:
            key = f"{artist.lower()} - {title.lower()}"
            results.append((title, artist, key))
    results.reverse()  # oldest first
    return results

def create_playlist(access_token, volume):
    name = f"{PLAYLIST_PREFIX} — Vol. {volume}"
    playlist = api_tool.call(
        "spotify_web_api.create_playlist",
        {
            "access_token": access_token,
            "user_id": SP_USER_ID,
            "name": name,
            "description": f"Archive of SiriusXM 1st Wave, volume {volume} (auto-generated).",
            "public": False
        }
    )
    logging.info("Created playlist %s (id=%s)", name, playlist["id"])
    return playlist["id"]

def get_playlist_total_tracks(access_token, playlist_id):
    playlist = api_tool.call(
        "spotify_web_api.get_playlist",
        {
            "access_token": access_token,
            "playlist_id": playlist_id,
            "fields": "tracks.total"
        }
    )
    return playlist["tracks"]["total"]

def search_track(access_token, title, artist):
    """Return the first Spotify track URI or None."""
    result = api_tool.call(
        "spotify_web_api.search_track",
        {
            "access_token": access_token,
            "query": f"{title} {artist}",
            "limit": 1
        }
    )
    items = result.get("tracks", [])
    return items[0]["uri"] if items else None

def add_tracks(access_token, playlist_id, uris):
    if not uris:
        return True
    for i in range(0, len(uris), 100):
        chunk = uris[i:i+100]
        api_tool.call(
            "spotify_web_api.add_tracks_to_playlist",
            {
                "access_token": access_token,
                "playlist_id": playlist_id,
                "track_uris": chunk
            }
        )
        time.sleep(0.2)
    return True

# ---------------- Main ----------------

def main():
    meta = load_json(META_FILE, default={})
    seen = set(load_json(SEEN_FILE, default=[]))

    current_volume = meta.get("current_volume", 1)
    current_playlist_id = meta.get("current_playlist_id")

    access_token = get_access_token()

    if not current_playlist_id:
        current_playlist_id = create_playlist(access_token, current_volume)
        meta["current_volume"] = current_volume
        meta["current_playlist_id"] = current_playlist_id
        save_json(META_FILE, meta)

    try:
        total = get_playlist_total_tracks(access_token, current_playlist_id)
    except Exception as e:
        logging.warning("Playlist missing, creating new: %s", e)
        current_volume += 1
        current_playlist_id = create_playlist(access_token, current_volume)
        meta["current_volume"] = current_volume
        meta["current_playlist_id"] = current_playlist_id
        save_json(META_FILE, meta)
        total = 0

    if total >= PLAYLIST_THRESHOLD:
        logging.info("Playlist at threshold, creating new volume.")
        current_volume += 1
        current_playlist_id = create_playlist(access_token, current_volume)
        meta["current_volume"] = current_volume
        meta["current_playlist_id"] = current_playlist_id
        save_json(META_FILE, meta)
        total = 0

    xm_tracks = fetch_xm_tracks()
    logging.info("Fetched %d XM tracks.", len(xm_tracks))

    to_add = []
    new_count = 0

    for title, artist, key in xm_tracks:
        if key in seen:
            continue
        uri = search_track(access_token, title, artist)
        if uri:
            if total + len(to_add) + 1 > PLAYLIST_MAX:
                if to_add:
                    add_tracks(access_token, current_playlist_id, to_add)
                    total += len(to_add)
                    to_add = []
                current_volume += 1
                current_playlist_id = create_playlist(access_token, current_volume)
                meta["current_volume"] = current_volume
                meta["current_playlist_id"] = current_playlist_id
                save_json(META_FILE, meta)
                total = 0

            to_add.append(uri)
            seen.add(key)
            new_count += 1
        else:
            logging.info("Not found: %s — %s", artist, title)
            seen.add(key)

        if len(to_add) >= 50:
            add_tracks(access_token, current_playlist_id, to_add)
            total += len(to_add)
            to_add = []
            save_json(SEEN_FILE, list(seen))
            save_json(META_FILE, meta)

    if to_add:
        add_tracks(access_token, current_playlist_id, to_add)

    save_json(SEEN_FILE, list(seen))
    save_json(META_FILE, meta)
    logging.info("Done. Added %d new tracks.", new_count)


if __name__ == "__main__":
    main()
