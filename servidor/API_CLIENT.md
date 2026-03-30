# Radio Monitor API - Client Documentation

API documentation for client applications connecting to the Mundo Livre FM Radio Monitor service.

## Table of Contents
- [Introduction](#introduction)
- [API Reference](#api-reference)
- [Data Models](#data-models)
- [Code Examples](#code-examples)
- [Best Practices](#best-practices)
- [Implementation Strategy](#implementation-strategy)

---

## Introduction

### Base URLs

| Environment | URL |
|-------------|-----|
| Local Development | `http://localhost:8000` |
| VPS Production | `http://167.126.18.152:8000` |

### Authentication

No authentication required. The API is open for read access.

### CORS

CORS is enabled for all origins, making it easy to use from web applications.

---

## API Reference

### GET `/`
Health check endpoint.

**Response:**
```json
{
  "status": "Radio Monitor API is running"
}
```

---

### GET `/now`
Get the current radio status - either the currently playing song, an active commercial interval, or a special program like "A Voz do Brasil".

**Response (Playing):**
```json
{
  "status": "playing",
  "song_id": 123,
  "voz_entry_id": null
}
```

**Response (Commercial Interval):**
```json
{
  "status": "interval",
  "song_id": null,
  "voz_entry_id": null
}
```

**Response (Voz do Brasil):**
```json
{
  "status": "voz_do_brasil",
  "song_id": null,
  "voz_entry_id": 45
}
```

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `status` | string | Either `"playing"`, `"interval"`, or `"voz_do_brasil"` |
| `song_id` | number\|null | The ID of the current song, or `null` during commercials/special programs |
| `voz_entry_id` | number\|null | The ID of the Voz do Brasil entry (only when status is `"voz_do_brasil"`) |

---

### GET `/history`
Get the history of played songs with pagination.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum number of records to return (1-1000) |
| `offset` | integer | 0 | Number of records to skip for pagination |

**Example:** `GET /history?limit=50&offset=100`

**Response:**
```json
[
  {
    "id": 123,
    "title": "Song Title",
    "artist": "Artist Name",
    "program": "Program Name",
    "announcer": "DJ Name",
    "popularity": 75,
    "cover_url": "https://i.scdn.co/image/...",
    "played_at": "2025-01-26T10:30:00"
  }
]
```

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique song identifier |
| `title` | string | Song title |
| `artist` | string | Artist name |
| `program` | string | Radio program name |
| `announcer` | string | Announcer/DJ name |
| `popularity` | integer | Spotify popularity score (0-100) |
| `cover_url` | string | Spotify album cover URL (may be empty) |
| `played_at` | string | ISO 8601 timestamp when the song started playing |

---

### GET `/intervals`
Get the history of commercial intervals.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 100 | Maximum number of records to return (1-1000) |
| `offset` | integer | 0 | Number of records to skip for pagination |

**Example:** `GET /intervals?limit=50&offset=0`

**Response:**
```json
[
  {
    "id": 1,
    "start_time": "2025-01-26T10:15:00",
    "end_time": "2025-01-26T10:18:30",
    "duration_seconds": 210
  }
]
```

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique interval identifier |
| `start_time` | string | ISO 8601 timestamp when interval started |
| `end_time` | string | ISO 8601 timestamp when interval ended |
| `duration_seconds` | integer | Length of the interval in seconds |

---

### GET `/special-programs`
Get the history of special programs like "A Voz do Brasil".

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | integer | 20 | Maximum number of records to return |

**Example:** `GET /special-programs?limit=50`

**Response:**
```json
[
  {
    "id": 1,
    "title": "A Voz do Brasil",
    "program": "Jornalismo",
    "announcer": "Locutor Oficial",
    "started_at": "2025-01-26T12:00:00"
  }
]
```

**Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique program identifier |
| `title` | string | Program title |
| `program` | string | Program category/name |
| `announcer` | string | Announcer name (may be null) |
| `started_at` | string | ISO 8601 timestamp when program started |
| `program_type` | string | Type of special program (e.g., "voz_do_brasil") |

**Note:** These programs are separate from regular songs and commercial intervals. They are mandatory broadcasts (like "A Voz do Brasil") that users may want to block similar to ads.

---

## Data Models

### NowPlayingResponse
```typescript
interface NowPlayingResponse {
  status: 'playing' | 'interval' | 'voz_do_brasil';
  song_id: number | null;
  voz_entry_id: number | null;
}
```

### SongResponse
```typescript
interface SongResponse {
  id: number;
  title: string;
  artist: string;
  program: string;
  announcer: string;
  popularity: number;
  cover_url: string;
  played_at: string;  // ISO 8601 timestamp
}
```

### IntervalResponse
```typescript
interface IntervalResponse {
  id: number;
  start_time: string;  // ISO 8601 timestamp
  end_time: string;    // ISO 8601 timestamp
  duration_seconds: number;
}
```

### VozDoBrasilResponse
```typescript
interface VozDoBrasilResponse {
  id: number;
  title: string;
  program: string;
  announcer: string | null;
  started_at: string;  // ISO 8601 timestamp
}
```

---

## Code Examples

### Python Example

Complete monitoring loop with change detection:

```python
import requests
import time
from typing import Optional

BASE_URL = "http://167.126.18.152:8000"

class RadioMonitor:
    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.last_song_id: Optional[int] = None

    def get_now(self) -> dict:
        """Get current radio status."""
        try:
            response = requests.get(f"{self.base_url}/now", timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching /now: {e}")
            return {"status": "error", "song_id": None}

    def get_history(self, limit: int = 10) -> list:
        """Get recent song history."""
        try:
            response = requests.get(f"{self.base_url}/history", params={"limit": limit}, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching /history: {e}")
            return []

    def get_intervals(self, limit: int = 10) -> list:
        """Get recent commercial intervals."""
        try:
            response = requests.get(f"{self.base_url}/intervals", params={"limit": limit}, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching /intervals: {e}")
            return []

    def get_special_programs(self, limit: int = 10) -> list:
        """Get recent special programs (A Voz do Brasil, etc)."""
        try:
            response = requests.get(f"{self.base_url}/special-programs", params={"limit": limit}, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching /special-programs: {e}")
            return []

    def check_changes(self) -> Optional[dict]:
        """Check if the current song has changed."""
        now = self.get_now()

        if now["status"] == "playing":
            current_song_id = now.get("song_id")

            if current_song_id != self.last_song_id:
                self.last_song_id = current_song_id

                # Fetch the current song details
                history = self.get_history(limit=1)
                if history:
                    return {
                        "type": "song_change",
                        "song": history[0]
                    }

        elif now["status"] == "voz_do_brasil":
            # Voz do Brasil is playing (can be blocked like ads)
            voz_entry_id = now.get("voz_entry_id")
            if voz_entry_id:
                programs = self.get_special_programs(limit=1)
                if programs:
                    return {
                        "type": "voz_do_brasil_start",
                        "program": programs[0]
                    }

        elif now["status"] == "interval" and self.last_song_id is not None:
            # Transitioned to commercial interval
            self.last_song_id = None
            return {
                "type": "interval_start"
            }

        return None

    def monitor_loop(self, poll_interval: int = 15):
        """Run the monitoring loop."""
        print(f"Starting radio monitor (polling every {poll_interval}s)...")

        while True:
            try:
                change = self.check_changes()

                if change:
                    if change["type"] == "song_change":
                        song = change["song"]
                        print(f"NOW PLAYING: {song['title']} - {song['artist']}")
                        print(f"  Program: {song['program']} | Announcer: {song['announcer']}")
                        print(f"  Popularity: {song['popularity']}")
                    elif change["type"] == "interval_start":
                        print("COMMERCIAL INTERVAL STARTED")
                    elif change["type"] == "voz_do_brasil_start":
                        program = change["program"]
                        print(f"📢 SPECIAL PROGRAM: {program['title']}")
                        print(f"  (User may choose to block this)")

            except KeyboardInterrupt:
                print("\nStopping monitor...")
                break
            except Exception as e:
                print(f"Error in monitor loop: {e}")

            time.sleep(poll_interval)


if __name__ == "__main__":
    monitor = RadioMonitor()
    monitor.monitor_loop(poll_interval=15)
```

---

### TypeScript Example

React-ready example with interfaces:

```typescript
// types.ts
export interface NowPlayingResponse {
  status: 'playing' | 'interval' | 'voz_do_brasil';
  song_id: number | null;
  voz_entry_id: number | null;
}

export interface SongResponse {
  id: number;
  title: string;
  artist: string;
  program: string;
  announcer: string;
  popularity: number;
  cover_url: string;
  played_at: string;
}

export interface IntervalResponse {
  id: number;
  start_time: string;
  end_time: string;
  duration_seconds: number;
}

export interface VozDoBrasilResponse {
  id: number;
  title: string;
  program: string;
  announcer: string | null;
  started_at: string;
}

// api.ts
const BASE_URL = 'http://167.126.18.152:8000';

class RadioMonitorAPI {
  private baseUrl: string;

  constructor(baseUrl: string = BASE_URL) {
    this.baseUrl = baseUrl;
  }

  async getNow(): Promise<NowPlayingResponse> {
    const response = await fetch(`${this.baseUrl}/now`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async getHistory(limit: number = 100, offset: number = 0): Promise<SongResponse[]> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString()
    });
    const response = await fetch(`${this.baseUrl}/history?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async getIntervals(limit: number = 100, offset: number = 0): Promise<IntervalResponse[]> {
    const params = new URLSearchParams({
      limit: limit.toString(),
      offset: offset.toString()
    });
    const response = await fetch(`${this.baseUrl}/intervals?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async getSpecialPrograms(limit: number = 20): Promise<VozDoBrasilResponse[]> {
    const params = new URLSearchParams({
      limit: limit.toString()
    });
    const response = await fetch(`${this.baseUrl}/special-programs?${params}`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
}

export const radioAPI = new RadioMonitorAPI();

// React Hook Example
import { useState, useEffect } from 'react';
import { radioAPI, SongResponse, VozDoBrasilResponse } from './api';

interface NowPlayingState {
  song: SongResponse | null;
  specialProgram: VozDoBrasilResponse | null;
  isInterval: boolean;
  isVozDoBrasil: boolean;
}

function useNowPlaying() {
  const [state, setState] = useState<NowPlayingState>({
    song: null,
    specialProgram: null,
    isInterval: false,
    isVozDoBrasil: false
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let lastSongId: number | null = null;
    let lastVozId: number | null = null;

    const poll = async () => {
      try {
        const now = await radioAPI.getNow();

        if (now.status === 'playing' && now.song_id !== lastSongId) {
          lastSongId = now.song_id;
          const history = await radioAPI.getHistory(1);
          setState({
            song: history[0] || null,
            specialProgram: null,
            isInterval: false,
            isVozDoBrasil: false
          });
        } else if (now.status === 'voz_do_brasil' && now.voz_entry_id !== lastVozId) {
          lastVozId = now.voz_entry_id;
          const programs = await radioAPI.getSpecialPrograms(1);
          setState({
            song: null,
            specialProgram: programs[0] || null,
            isInterval: false,
            isVozDoBrasil: true
          });
        } else if (now.status === 'interval') {
          lastSongId = null;
          lastVozId = null;
          setState({
            song: null,
            specialProgram: null,
            isInterval: true,
            isVozDoBrasil: false
          });
        }

        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
      } finally {
        setLoading(false);
      }
    };

    poll(); // Initial fetch
    const interval = setInterval(poll, 15000); // Poll every 15s

    return () => clearInterval(interval);
  }, []);

  return { ...state, loading, error };
}

// Usage in component
function NowPlayingDisplay() {
  const { song, specialProgram, isInterval, isVozDoBrasil, loading, error } = useNowPlaying();

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;
  if (isInterval) return <div>Commercial Interval</div>;
  if (isVozDoBrasil && specialProgram) {
    return (
      <div className="special-program">
        <h2>📢 {specialProgram.title}</h2>
        <p>Program: {specialProgram.program}</p>
        {specialProgram.announcer && <small>{specialProgram.announcer}</small>}
        <p className="note">This program can be blocked in settings</p>
      </div>
    );
  }
  if (!song) return <div>No song playing</div>;

  return (
    <div className="now-playing">
      <img src={song.cover_url} alt="Cover" className="cover" />
      <h2>{song.title}</h2>
      <p>{song.artist}</p>
      <small>{song.program} • {song.announcer}</small>
    </div>
  );
}
```

---

### cURL Examples

Test the API from the command line:

```bash
# Health check
curl http://167.126.18.152:8000/

# Get current status
curl http://167.126.18.152:8000/now

# Get recent history
curl http://167.126.18.152:8000/history

# Get history with pagination
curl "http://167.126.18.152:8000/history?limit=50&offset=100"

# Get recent intervals
curl http://167.126.18.152:8000/intervals

# Get special programs (A Voz do Brasil, etc)
curl http://167.126.18.152:8000/special-programs

# Pretty print JSON
curl -s http://167.126.18.152:8000/history | jq '.'
```

---

## Best Practices

### 1. Polling Interval
- **Recommended:** 10-15 seconds between requests
- The monitoring server updates every 15 seconds
- More frequent polling provides no benefit and wastes resources

### 2. Error Handling
- Always implement timeout handling (recommend 5-10 seconds)
- Use exponential backoff for repeated failures
- Gracefully degrade when the API is unavailable
- Cache last known state locally for offline scenarios

### 3. Local Caching
```python
# Maintain local SQLite cache
# Update only when song_id changes
# Allows offline access to recent history
```

### 4. Commercial Interval Detection
- When `/now` returns `status: "interval"`, a commercial break is active
- The server automatically detects intervals by blocklisted terms:
  - "MUNDO LIVRE", "INTERVALO", "COMERCIAL", "AUDIO", "VINHETA", "RADIO"
- Use this state to hide player UI or show "Commercial Break" message

### 5. Cover Images
- The `cover_url` field may be empty string if no Spotify match
- Always validate URL before displaying
- Provide fallback image for missing covers

---

## Implementation Strategy

### Recommended Client Architecture

```

                         Client Application

  ┌──────────────┐      ┌──────────────┐      ┌──────────┐
  │   Poll Loop  │─────▶│ Detect State │─────▶│ Update UI│
  │   (15s)      │      │   Change     │      │          │
  └──────────────┘      └──────────────┘      └──────────┘
         │                      │
         ▼                      ▼
  ┌──────────────┐      ┌──────────────┐
  │ GET /now     │      │ GET /history │
  │              │      │ (if changed) │
  └──────────────┘      └──────────────┘
         │
         ▼
  ┌──────────────┐
  │ Local Cache  │
  │ (SQLite)     │
  └──────────────┘

         │                                     │
         ▼                                     ▼
┌─────────────────┐                   ┌─────────────────┐
│  Radio Monitor  │                   │   User Facing   │
│       API        │                   │   Interface     │
└─────────────────┘                   └─────────────────┘
```

### Step-by-Step Implementation

1. **Initialize State**
   ```python
   last_song_id = None
   local_cache = []
   ```

2. **Poll `/now` Endpoint**
   ```python
   status = poll("/now")  # Returns: {status: "playing", song_id: 123}
   ```

3. **Detect Changes**
   ```python
   if status["status"] == "playing" and status["song_id"] != last_song_id:
       # Song changed!
       last_song_id = status["song_id"]
   ```

4. **Fetch Details (if changed)**
   ```python
   if song_changed:
       history = poll("/history?limit=1")
       current_song = history[0]
   ```

5. **Update UI & Cache**
   ```python
   update_display(current_song)
   save_to_cache(current_song)
   ```

6. **Handle Commercials**
   ```python
   if status["status"] == "interval":
       show_commercial_message()
       last_song_id = None
   ```

7. **Repeat** (wait 15 seconds, go to step 2)

---

## Support

For issues or questions about the API:
- Check the API docs: `http://167.126.18.152:8000/docs`
- View the source code: `/home/ubuntu/radio-monitor` on VPS
- Contact the MundoAPP development team

---

*Last updated: January 2025*
