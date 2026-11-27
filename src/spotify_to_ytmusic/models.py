"""Pydantic models for Spotify tracks, YouTube Music matches, and sync reports."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SpotifyTrack(BaseModel):
    track_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str = ""
    duration_sec: int | None = None
    added_at: str | None = None

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    @property
    def search_query(self) -> str:
        artist_part = " ".join(self.artists[:2]).strip()
        if artist_part:
            return f"{self.title} {artist_part}"
        return self.title


class YTMusicMatch(BaseModel):
    spotify_track_id: str
    video_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    duration_sec: int | None = None
    score: float


class UnmatchedTrack(BaseModel):
    playlist: str
    track_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    reason: str


class PlaylistSyncReport(BaseModel):
    playlist_name: str
    playlist_id: str | None = None
    total_spotify: int
    matched: int
    added: int = 0
    moved: int = 0
    unmatched: list[UnmatchedTrack] = Field(default_factory=list)
