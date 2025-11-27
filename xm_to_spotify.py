import os
import requests
import time
import json
import cloudscraper

# --- CONFIGURATION ---
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN")

# Files to store state
XM_JSON_FILE = "xmplaylist.json"
STATE_FILE = "spotify_state.json" # Stores current playlist ID and Volume #

# Constants
XM_CHANNEL = "1stwave"
PLAYLIST_BASE_NAME = f"XM {XM_CHANNEL} Archive"
MAX_TRACKS_PER_REQUEST = 100
PLAYLIST_LIMIT = 9900 # Buffer below 10,000 to be safe

# --- AUTHENTICATION ---
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

def get_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

# --- SPOTIFY API HELPERS ---
def get_user_id(token):
    url = "https://api.spotify.com/v1/me"
    response = requests.get(url, headers=get_headers(token))
    response.raise_for_status()
    return response.json()["id"]

def get_playlist_size(token, playlist_id):
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
    response = requests.get(url, headers=get_headers(token))
    if response.status_code == 404:
        return None # Playlist was deleted or lost
    response.raise_for_status()
    return response.json()["tracks"]["total"]

def create_playlist(token, user_id, name):
    url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    data = {"name": name, "public": False, "description": "Auto-generated from XMPlaylist"}
    response = requests.post(url, headers=get_headers(token), json=data)
    response.raise_for_status()
    return response.json()["id"]

def rename_playlist(token, playlist_id, new_name):
    url = f"https://api.spotify.com/v1/playlists/{playlist_id}"
    data = {"name": new_name}
    requests.put(url, headers=get_headers(token), json=data)

def add_tracks(token, playlist_id, track_uris):
    # Filter out duplicates or handle batching
    for i in range(0, len(track_uris), MAX_TRACKS_PER_REQUEST):
        chunk = track_uris[i:i + MAX_TRACKS_PER_REQUEST]
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        requests.post(url, headers=get_headers(token), json={"uris": chunk})
        time.sleep(0.5)

# --- STATE MANAGEMENT ---
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"playlist_id": None, "volume": 1}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

# --- XM FETCHING ---
def fetch_xm_tracks():
    scraper = cloudscraper.create_scraper() # Fixes 403 Error
    try:
        url = f"https://xmplaylist.com/api/station/{XM_CHANNEL}"
        resp = scraper.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching XM: {e}")
        return []

    # Extract Spotify URIs
    uris = []
    for item in data.get("results", []):
        for link in item.get("links", []):
            if link["site"] == "spotify" and "/track/" in link["url"]:
                tid = link["url"].split("/track/")[1].split("?")[0]
                uris.append(f"spotify:track:{tid}")
                break
    return uris

# --- MAIN LOGIC ---
if __name__ == "__main__":
    print("Starting sync...")
    token = get_access_token()
    state = load_state()
    
    current_id = state.get("playlist_id")
    current_vol = state.get("volume", 1)
    
    # 1. Check if we need a new playlist (First run, or current is full/deleted)
    need_new_playlist = False
    
    if not current_id:
        need_new_playlist = True
    else:
        size = get_playlist_size(token, current_id)
        if size is None:
            print("Current playlist not found. Creating new one.")
            need_new_playlist = True
        elif size >= PLAYLIST_LIMIT:
            print(f"Playlist Full ({size} tracks). Rotating...")
            # Rename the old one to lock it in history
            rename_playlist(token, current_id, f"{PLAYLIST_BASE_NAME} - Vol {current_vol}")
            current_vol += 1
            need_new_playlist = True
    
    # 2. Create new playlist if needed
    if need_new_playlist:
        user_id = get_user_id(token)
        # We name the current one "Current" or "Latest" so it's easy to find
        new_name = f"{PLAYLIST_BASE_NAME} - Vol {current_vol} (Current)"
        current_id = create_playlist(token, user_id, new_name)
        print(f"Created new playlist: {new_name}")
        
        # Update State
        state["playlist_id"] = current_id
        state["volume"] = current_vol
        save_state(state)

    # 3. Add Tracks
    tracks = fetch_xm_tracks()
    if tracks:
        print(f"Adding {len(tracks)} tracks to Volume {current_vol}...")
        add_tracks(token, current_id, tracks)
        print("Done.")
    else:
        print("No tracks found on XMPlaylist.")

    # 4. Save state one last time to be sure
    save_state(state)
