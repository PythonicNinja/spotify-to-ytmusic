"""Unit tests for Exportify CSV parsing, auth parsing, matching, reordering, and sync."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

from spotify_to_ytmusic.auth import extract_headers
from spotify_to_ytmusic.cli import main as cli_main
from spotify_to_ytmusic.matcher import fold_diacritics, score_candidate
from spotify_to_ytmusic.models import SpotifyTrack
from spotify_to_ytmusic.ordering import apply_moves, compute_reorder_moves
from spotify_to_ytmusic.playlists import load_playlist_file
from spotify_to_ytmusic.sync import sync_playlist_file


def test_load_exportify_csv_sorts_by_added_at_recency(tmp_path: Path) -> None:
    csv_file = tmp_path / "Roadtrip.csv"
    csv_file.write_text(
        "Track URI,Track Name,Artist Name(s),Album Name,Duration (ms),Added At\n"
        "spotify:track:1111111111111111111111,Old Song,Artist A,Alb,200000,2023-01-01T10:00:00Z\n"
        "spotify:track:2222222222222222222222,New Song,Artist B,Alb,180000,2026-05-01T12:00:00Z\n"
        "spotify:track:2222222222222222222222,New Song,Artist B,Alb,180000,2026-05-01T12:00:00Z\n"
        "spotify:track:3333333333333333333333,Mid Song,Artist C,Alb,210000,2024-06-01T12:00:00Z\n",
        encoding="utf-8",
    )

    newest_first = load_playlist_file(csv_file, reverse=False)
    assert [t.track_id for t in newest_first.tracks] == [
        "2222222222222222222222",
        "3333333333333333333333",
        "1111111111111111111111",
    ]
    assert newest_first.tracks[0].duration_sec == 180

    oldest_first = load_playlist_file(csv_file, reverse=True)
    assert [t.track_id for t in oldest_first.tracks] == [
        "1111111111111111111111",
        "3333333333333333333333",
        "2222222222222222222222",
    ]


def test_cli_check_command(tmp_path: Path) -> None:
    csv_file = tmp_path / "Chill.csv"
    csv_file.write_text(
        "Track URI,Track Name,Artist Name(s),Album Name,Duration (ms),Added At\n"
        "spotify:track:1111111111111111111111,Song A,Artist 1,Alb,200000,2026-03-01T00:00:00Z\n",
        encoding="utf-8",
    )
    assert cli_main(["check", "--playlists-dir", str(tmp_path)]) == 0


def test_extract_headers_all_browser_formats() -> None:
    curl_cmd = """
    curl 'https://music.youtube.com/youtubei/v1/browse' \\
      -H 'accept: */*' \\
      -H 'x-goog-authuser: 0' \\
      -b 'SID=abc; SAPISID=xyz' \\
      --data-raw $'{"context":{"client":{"hl":"en"}}}'
    """
    parsed_curl = extract_headers(curl_cmd)
    assert parsed_curl["cookie"] == "SID=abc; SAPISID=xyz"
    assert parsed_curl["x-goog-authuser"] == "0"

    chrome_two_line = """
    Request Headers
    :authority
    music.youtube.com
    :method
    POST
    accept
    */*
    cookie
    SID=abc; SAPISID=xyz
    x-goog-authuser
    0
    """
    parsed_chrome = extract_headers(chrome_two_line)
    assert parsed_chrome["cookie"] == "SID=abc; SAPISID=xyz"
    assert parsed_chrome["x-goog-authuser"] == "0"

    fetch_text = """fetch("https://music.youtube.com/youtubei/v1/browse", {
      "headers": {
        "cookie": "SID=abc; SAPISID=xyz",
        "x-goog-authuser": "0"
      }
    });"""
    parsed_fetch = extract_headers(fetch_text)
    assert parsed_fetch["cookie"] == "SID=abc; SAPISID=xyz"
    assert parsed_fetch["x-goog-authuser"] == "0"

    firefox_raw = (
        "POST /youtubei/v1/browse?prettyPrint=false HTTP/2\n"
        "Cookie: SID=abc; SAPISID=xyz\n"
        "X-Goog-AuthUser: 0\n"
    )
    parsed_ff = extract_headers(firefox_raw)
    assert parsed_ff["cookie"] == "SID=abc; SAPISID=xyz"
    assert parsed_ff["x-goog-authuser"] == "0"


def test_score_candidate_prefers_official_song_with_matching_duration() -> None:
    track = SpotifyTrack(
        track_id="abc",
        title="Blinding Lights",
        artists=["The Weeknd"],
        duration_sec=200,
    )
    official_song = {
        "videoId": "vid1",
        "title": "Blinding Lights",
        "artists": [{"name": "The Weeknd"}],
        "duration_seconds": 201,
        "resultType": "song",
    }
    hour_loop = {
        "videoId": "vid2",
        "title": "Blinding Lights (1 Hour Loop)",
        "artists": [{"name": "Random Channel"}],
        "duration_seconds": 3600,
        "resultType": "video",
    }
    assert score_candidate(track, official_song) > 0.95
    assert score_candidate(track, official_song) > score_candidate(track, hour_loop) + 0.4


def test_fold_diacritics_matches_polish_names() -> None:
    assert fold_diacritics("Oznaczone gwiazdką") == "oznaczone gwiazdka"
    assert fold_diacritics("Dżem - List Do M. łódź") == "dzem - list do m. lodz"


def test_compute_reorder_moves_exhaustive_permutations() -> None:
    target = ["a", "b", "c", "d", "e"]
    for perm in itertools.permutations(target):
        current = list(perm)
        moves = compute_reorder_moves(current, target)
        reordered = apply_moves(current, moves)
        assert reordered == target
        assert len(moves) <= len(target)


def test_compute_reorder_moves_with_extra_tracks() -> None:
    current = ["x1", "d", "a", "x2", "c", "b", "x3"]
    target = ["a", "b", "c", "d"]
    moves = compute_reorder_moves(current, target)
    reordered = apply_moves(current, moves)
    filtered = [item for item in reordered if item in target]
    assert filtered == target


class _FakeYTMusic:
    def __init__(self, initial_tracks: list[tuple[str, str]] | None = None) -> None:
        self.playlists: dict[str, list[tuple[str, str]]] = {}
        self._counter = 0
        if initial_tracks is not None:
            self.playlists["PL_EXISTING"] = list(initial_tracks)

    def search(self, query: str, filter: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        catalog = {
            "Song A": ("vidA", "Artist 1", 200),
            "Song B": ("vidB", "Artist 2", 180),
            "Song C": ("vidC", "Artist 3", 210),
        }
        for title, (vid, artist, dur) in catalog.items():
            if title in query:
                return [
                    {
                        "videoId": vid,
                        "title": title,
                        "artists": [{"name": artist}],
                        "duration_seconds": dur,
                        "resultType": "song",
                    }
                ]
        return []

    def create_playlist(self, title: str, description: str, privacy_status: str = "PRIVATE") -> str:
        pid = f"PL_{title}"
        self.playlists[pid] = []
        return pid

    def get_playlist(self, playlist_id: str, limit: int | None = None) -> dict[str, Any]:
        return {
            "id": playlist_id,
            "tracks": [
                {"videoId": vid, "setVideoId": svid} for vid, svid in self.playlists[playlist_id]
            ],
        }

    def add_playlist_items(
        self, playlist_id: str, video_ids: list[str], duplicates: bool = False
    ) -> str:
        new_items: list[tuple[str, str]] = []
        for vid in video_ids:
            self._counter += 1
            new_items.append((vid, f"set_{self._counter}"))
        # Matches YouTube Music addToTop=True: prepends batch preserving in-batch order
        self.playlists[playlist_id] = new_items + self.playlists[playlist_id]
        return "STATUS_SUCCEEDED"

    def remove_playlist_items(self, playlist_id: str, items: list[dict[str, str]]) -> str:
        remove_ids = {item["setVideoId"] for item in items}
        self.playlists[playlist_id] = [
            pair for pair in self.playlists[playlist_id] if pair[1] not in remove_ids
        ]
        return "STATUS_SUCCEEDED"

    def edit_playlist(
        self,
        playlist_id: str,
        moveItem: str | tuple[str, str] | None = None,
        addToTop: bool | None = None,
        sortOrder: Any = None,
    ) -> str:
        items = self.playlists[playlist_id]
        if isinstance(moveItem, str):
            idx = next(i for i, (_, svid) in enumerate(items) if svid == moveItem)
            pair = items.pop(idx)
            items.append(pair)
        elif isinstance(moveItem, tuple):
            src, dst = moveItem
            src_idx = next(i for i, (_, svid) in enumerate(items) if svid == src)
            pair = items.pop(src_idx)
            dst_idx = next(i for i, (_, svid) in enumerate(items) if svid == dst)
            items.insert(dst_idx, pair)
        return "STATUS_SUCCEEDED"


def test_sync_playlist_adds_missing_and_reorders_to_exact_recency(tmp_path: Path) -> None:
    csv_file = tmp_path / "Favorites.csv"
    csv_file.write_text(
        "Track URI,Track Name,Artist Name(s),Album Name,Duration (ms),Added At\n"
        "spotify:track:1111111111111111111111,Song A,Artist 1,Alb,200000,2026-03-01T00:00:00Z\n"
        "spotify:track:2222222222222222222222,Song B,Artist 2,Alb,180000,2026-02-01T00:00:00Z\n"
        "spotify:track:3333333333333333333333,Song C,Artist 3,Alb,210000,2026-01-01T00:00:00Z\n",
        encoding="utf-8",
    )

    fake_yt = _FakeYTMusic(initial_tracks=[("vidC", "set_old_c"), ("vidA", "set_old_a")])
    library_index = {"favorites": "PL_EXISTING"}

    report = sync_playlist_file(
        yt=fake_yt,  # type: ignore[arg-type]
        playlist_path=csv_file,
        cache_dir=tmp_path / "cache",
        library_index=library_index,
    )

    assert report.total_spotify == 3
    assert report.matched == 3
    assert report.added == 1
    assert [vid for vid, _ in fake_yt.playlists["PL_EXISTING"]] == ["vidA", "vidB", "vidC"]
