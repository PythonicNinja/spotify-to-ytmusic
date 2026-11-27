"""Parse Exportify CSV playlists sorted by Added At recency."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from spotify_to_ytmusic.models import SpotifyTrack

TRACK_ID_RE = re.compile(
    r"(?:open\.spotify\.com/(?:intl-[a-z-]+/)?track/|spotify:track:)([A-Za-z0-9]{22})"
)


@dataclass(frozen=True)
class PlaylistInput:
    name: str
    path: Path
    tracks: list[SpotifyTrack]


def extract_track_id(text: str) -> str | None:
    match = TRACK_ID_RE.search(text)
    return match.group(1) if match else None


def _parse_duration_ms(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return max(1, round(int(raw) / 1000))
    except ValueError:
        return None


def load_playlist_file(path: Path, reverse: bool = False) -> PlaylistInput:
    rows: list[tuple[str, int, SpotifyTrack]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            uri = row.get("Track URI") or row.get("track_uri") or ""
            track_id = extract_track_id(uri)
            title = (row.get("Track Name") or row.get("track_name") or "").strip()
            if not track_id or not title:
                continue
            artists_raw = row.get("Artist Name(s)") or row.get("artist_name") or ""
            artists = [a.strip() for a in artists_raw.split(";") if a.strip()]
            album = (row.get("Album Name") or row.get("album_name") or "").strip()
            added_at = (row.get("Added At") or row.get("added_at") or "").strip() or None
            duration_sec = _parse_duration_ms(row.get("Duration (ms)") or row.get("duration_ms"))
            track = SpotifyTrack(
                track_id=track_id,
                title=title,
                artists=artists,
                album=album,
                duration_sec=duration_sec,
                added_at=added_at,
            )
            rows.append((added_at or "", idx, track))

    if any(added_at for added_at, _, _ in rows):
        rows.sort(key=lambda item: (item[0], item[1]), reverse=not reverse)
    elif reverse:
        rows.reverse()

    seen: set[str] = set()
    tracks: list[SpotifyTrack] = []
    for _, _, track in rows:
        if track.track_id not in seen:
            seen.add(track.track_id)
            tracks.append(track)

    return PlaylistInput(name=path.stem, path=path, tracks=tracks)


def discover_playlist_files(playlists_dir: Path, only_name: str | None = None) -> list[Path]:
    if not playlists_dir.exists():
        return []
    files = sorted(
        path for path in playlists_dir.iterdir() if path.is_file() and path.suffix.lower() == ".csv"
    )
    if only_name:
        target = only_name.strip().lower()
        return [p for p in files if p.stem.lower() == target or p.name.lower() == target]
    return files
