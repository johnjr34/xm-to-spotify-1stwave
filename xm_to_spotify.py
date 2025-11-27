import os
import requests
import time
import json

# -------------------
# Spotify secrets from environment
# -------------------
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN")
PLAYLIST_ID = os.getenv("SPOTIFY_PLAYLIST_ID")  # Your target Spotify playlist

# -------------------
# Constants
# -------------------
XM_CHANNEL = "1stwave"
XM_JSON_FILE = "xmplaylist.json"
MAX_TRACKS_PER_REQUEST = 100
MAX_TRACKS_PER_PLAYLIST = 10000

# -------------------
# Spotify helpers
# -------------------
def get_access_token():
    url = "https://accounts.spotify.com/api/token"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]

def chunked(iterable, size):
    """Yield successive chunks of size `size` from iterable"""
    for i in range(0, len(iterable), size):
        yield iterable[i:i + size]

def add_tracks_to_playlist(playlist_id, track_uris):
    access_token = get_access_token()
    headers = {"Authorization": f"Bearer {access_token}"}

    if len(track_uris) > MAX_TRACKS_PER_PLAYLIST:
        track_uris = track_uris[:MAX_TRACKS_PER_PLAYLIST]
        print(f"Warning: Only adding first {MAX_TRACKS_PER_PLAYLIST} tracks due to Spotify limit.")

    for chunk in chunked(track_uris, MAX_TRACKS_PER_REQUEST):
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        data = {"uris": chunk}
        response = requests.post(url, json=data, headers=headers)
        if response.status_code not in [200, 201]:
            print("Error adding tracks:", response.json())
        time.sleep(0.1)  # avoid rate limits

# -------------------
# XMPlaylist fetch/update
# -------------------
def fetch_xmplaylist():
    headers = {"User-Agent": "xm-to-spotify-script"}
    url = f"https://xmplaylist.com/api/station/{XM_CHANNEL}"
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print("Error fetching XMPlaylist:", e)
        return []

    data = response.json()

    # Save/update local JSON
    with open(XM_JSON_FILE, "w") as f:
        json.dump(data, f, indent=2)

    # Extract Spotify track URIs
    track_uris = []
    for item in data.get("results", []):
        for link in item.get("links", []):
            if link.get("site") == "spotify":
                track_id = link["url"].split("/")[-1].split("?")[0]
                track_uris.append(f"spotify:track:{track_id}")
                break

    return track_uris

# -------------------
# Main
# -------------------
if __name__ == "__main__":
    tracks = fetch_xmplaylist()
    if not tracks:
        print("No tracks fetched from XMPlaylist.")
    else:
        add_tracks_to_playlist(PLAYLIST_ID, tracks)
        print(f"Added {len(tracks)} tracks to Spotify playlist.")
