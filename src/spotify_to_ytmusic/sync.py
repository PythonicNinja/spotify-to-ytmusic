"""Orchestrate Spotify CSV -> YouTube Music playlist syncing with exact recency order."""

from __future__ import annotations

import contextlib
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ytmusicapi import YTMusic
from ytmusicapi.models.content.enums import PlaylistSortOrder

from spotify_to_ytmusic.cache import load_model_cache, save_model_cache
from spotify_to_ytmusic.matcher import (
    extract_candidate_artists,
    find_best_match,
    fold_diacritics,
    normalize_text,
    parse_duration_seconds,
    score_candidate,
)
from spotify_to_ytmusic.models import (
    PlaylistSyncReport,
    SpotifyTrack,
    UnmatchedTrack,
    YTMusicMatch,
)
from spotify_to_ytmusic.ordering import compute_reorder_moves
from spotify_to_ytmusic.playlists import PlaylistInput, load_playlist_file

ADD_BATCH_SIZE = 50
ADD_BATCH_DELAY_SEC = 1.05
REMOVE_BATCH_SIZE = 50
MATCH_CHUNK_SIZE = 25
MATCH_WORKERS = 4


def _playlist_key(name: str) -> str:
    return " ".join(fold_diacritics(name).split())


def _index_library_playlists(yt: YTMusic) -> dict[str, str]:
    playlists = yt.get_library_playlists(limit=None) or []
    index: dict[str, str] = {}
    for item in playlists:
        title = str(item.get("title") or "").strip()
        playlist_id = str(item.get("playlistId") or "").strip()
        key = _playlist_key(title)
        if key and playlist_id and key not in index:
            index[key] = playlist_id
    return index


def _extract_playlist_items(playlist_data: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for track in playlist_data.get("tracks") or []:
        video_id = track.get("videoId")
        set_video_id = track.get("setVideoId")
        if video_id and set_video_id:
            items.append((str(video_id), str(set_video_id)))
    return items


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _add_in_batches(
    yt: YTMusic,
    playlist_id: str,
    video_ids: list[str],
    batch_delay_sec: float = ADD_BATCH_DELAY_SEC,
) -> list[str]:
    """Add tracks using addToTop=True by sending newest-first chunks in reverse batch order.

    This preserves exact top-to-bottom order under both NEWEST_FIRST and MANUAL sort modes.
    """
    failed: list[str] = []
    batches = [
        video_ids[start : start + ADD_BATCH_SIZE]
        for start in range(0, len(video_ids), ADD_BATCH_SIZE)
    ]
    total = len(video_ids)
    added_so_far = 0
    for batch_idx, batch in enumerate(reversed(batches)):
        try:
            yt.add_playlist_items(playlist_id, batch, duplicates=False)
        except Exception:
            for video_id in reversed(batch):
                try:
                    yt.add_playlist_items(playlist_id, [video_id], duplicates=False)
                except Exception:
                    failed.append(video_id)
        added_so_far += len(batch)
        if total > ADD_BATCH_SIZE:
            print(f"  added {added_so_far}/{total} tracks...", flush=True)
        if batch_delay_sec > 0 and batch_idx + 1 < len(batches):
            time.sleep(batch_delay_sec)
    return failed


def _clear_playlist_items(
    yt: YTMusic,
    playlist_id: str,
    existing_items: list[tuple[str, str]],
) -> None:
    payload = [{"videoId": vid, "setVideoId": svid} for vid, svid in existing_items]
    total = len(payload)
    for start in range(0, total, REMOVE_BATCH_SIZE):
        batch = payload[start : start + REMOVE_BATCH_SIZE]
        try:
            yt.remove_playlist_items(playlist_id, batch)
        except Exception:
            for item in batch:
                with contextlib.suppress(Exception):
                    yt.remove_playlist_items(playlist_id, [item])
        done = min(start + len(batch), total)
        if total > REMOVE_BATCH_SIZE:
            print(f"  cleared {done}/{total} existing tracks...", flush=True)


def _apply_reorder(
    yt: YTMusic,
    playlist_id: str,
    moves: list[tuple[str, str | None]],
) -> None:
    total = len(moves)
    for idx, (set_video_id, successor_id) in enumerate(moves, 1):
        move_arg: str | tuple[str, str] = (
            set_video_id if successor_id is None else (set_video_id, successor_id)
        )
        yt.edit_playlist(playlist_id, moveItem=move_arg)
        if total > 25 and (idx % 25 == 0 or idx == total):
            print(f"  reordered {idx}/{total} tracks...", flush=True)


def _index_existing_tracks_by_title(
    yt_tracks: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_title: dict[str, list[dict[str, Any]]] = {}
    for track in yt_tracks:
        title = normalize_text(str(track.get("title") or ""))
        if title and track.get("videoId"):
            by_title.setdefault(title, []).append(track)
    return by_title


def _reuse_existing_matches(
    playlist: PlaylistInput,
    match_cache: dict[str, YTMusicMatch],
    existing_tracks: list[dict[str, Any]],
    min_reuse_score: float = 0.85,
) -> int:
    if not existing_tracks:
        return 0
    by_title = _index_existing_tracks_by_title(existing_tracks)
    reused = 0
    for track in playlist.tracks:
        if track.track_id in match_cache:
            continue
        candidates = by_title.get(normalize_text(track.title), [])
        best_score = 0.0
        best_cand: dict[str, Any] | None = None
        for cand in candidates:
            score = score_candidate(track, cand)
            if score > best_score:
                best_score = score
                best_cand = cand
        if best_cand is not None and best_score >= min_reuse_score:
            match_cache[track.track_id] = YTMusicMatch(
                spotify_track_id=track.track_id,
                video_id=str(best_cand["videoId"]),
                title=str(best_cand.get("title") or ""),
                artists=extract_candidate_artists(best_cand),
                duration_sec=parse_duration_seconds(best_cand),
                score=best_score,
            )
            reused += 1
    return reused


def _match_track_worker(yt: YTMusic, track: SpotifyTrack) -> tuple[str, YTMusicMatch | None]:
    return track.track_id, find_best_match(yt, track)


def _match_playlist_tracks(
    yt: YTMusic,
    playlist: PlaylistInput,
    match_cache: dict[str, YTMusicMatch],
    matches_cache_path: Path,
) -> tuple[list[str], list[UnmatchedTrack]]:
    to_search = [track for track in playlist.tracks if track.track_id not in match_cache]

    if to_search:
        total = len(to_search)
        done = 0
        with ThreadPoolExecutor(max_workers=MATCH_WORKERS) as pool:
            for start in range(0, total, MATCH_CHUNK_SIZE):
                chunk = to_search[start : start + MATCH_CHUNK_SIZE]
                futures = [pool.submit(_match_track_worker, yt, track) for track in chunk]
                for future in futures:
                    track_id, match = future.result()
                    if match is not None:
                        match_cache[track_id] = match
                done += len(chunk)
                save_model_cache(matches_cache_path, match_cache)
                print(
                    f"  matched {done}/{total} new tracks on YTMusic "
                    f"(cache: {len(match_cache)})...",
                    flush=True,
                )

    desired_video_ids: list[str] = []
    unmatched: list[UnmatchedTrack] = []
    for track in playlist.tracks:
        match = match_cache.get(track.track_id)
        if match is None:
            unmatched.append(
                UnmatchedTrack(
                    playlist=playlist.name,
                    track_id=track.track_id,
                    title=track.title,
                    artists=track.artists,
                    reason="No confident YouTube Music match",
                )
            )
            continue
        desired_video_ids.append(match.video_id)

    return _dedupe_preserving_order(desired_video_ids), unmatched


def sync_playlist_file(
    yt: YTMusic,
    playlist_path: Path,
    cache_dir: Path,
    library_index: dict[str, str],
    privacy: str = "PRIVATE",
    reverse: bool = False,
    dry_run: bool = False,
    rebuild: bool = False,
) -> PlaylistSyncReport:
    playlist = load_playlist_file(playlist_path, reverse=reverse)
    matches_cache_path = cache_dir / "ytm_matches.json"

    playlist_key = _playlist_key(playlist.name)
    playlist_id = library_index.get(playlist_key)
    existing_tracks_raw: list[dict[str, Any]] = []
    existing_items: list[tuple[str, str]] = []
    if playlist_id:
        yt_playlist = yt.get_playlist(playlist_id, limit=None)
        existing_tracks_raw = list(yt_playlist.get("tracks") or [])
        existing_items = _extract_playlist_items(yt_playlist)

    match_cache = load_model_cache(matches_cache_path, YTMusicMatch)
    reused = _reuse_existing_matches(playlist, match_cache, existing_tracks_raw)
    if reused:
        save_model_cache(matches_cache_path, match_cache)
        print(f"  reused {reused} confident matches already in YTMusic playlist...", flush=True)

    desired_video_ids, unmatched = _match_playlist_tracks(
        yt, playlist, match_cache, matches_cache_path
    )
    save_model_cache(matches_cache_path, match_cache)

    if rebuild and playlist_id:
        missing_video_ids = list(desired_video_ids)
    else:
        existing_video_ids = {vid for vid, _ in existing_items}
        missing_video_ids = [vid for vid in desired_video_ids if vid not in existing_video_ids]

    if dry_run:
        if rebuild:
            planned_move_count = 0
        else:
            existing_set_by_vid = {vid: svid for vid, svid in existing_items}
            current_set_ids = [svid for _, svid in existing_items]
            target_set_ids = [
                existing_set_by_vid[vid] for vid in desired_video_ids if vid in existing_set_by_vid
            ]
            planned_move_count = len(compute_reorder_moves(current_set_ids, target_set_ids))
        return PlaylistSyncReport(
            playlist_name=playlist.name,
            playlist_id=playlist_id,
            total_spotify=len(playlist.tracks),
            matched=len(desired_video_ids),
            added=len(missing_video_ids),
            moved=planned_move_count,
            unmatched=unmatched,
        )

    if not playlist_id:
        created = yt.create_playlist(playlist.name, description="", privacy_status=privacy)
        if not isinstance(created, str):
            raise RuntimeError(f"Failed to create playlist {playlist.name!r}: {created}")
        playlist_id = created
        library_index[playlist_key] = playlist_id
    elif rebuild and existing_items:
        _clear_playlist_items(yt, playlist_id, existing_items)

    yt.edit_playlist(playlist_id, sortOrder=PlaylistSortOrder.NEWEST_FIRST, addToTop=True)

    if missing_video_ids:
        _add_in_batches(yt, playlist_id, missing_video_ids)

    refreshed = yt.get_playlist(playlist_id, limit=None)
    refreshed_items = _extract_playlist_items(refreshed)
    set_id_by_video_id: dict[str, str] = {}
    for vid, svid in refreshed_items:
        set_id_by_video_id.setdefault(vid, svid)

    current_set_ids = [svid for _, svid in refreshed_items]
    target_set_ids = [
        set_id_by_video_id[vid] for vid in desired_video_ids if vid in set_id_by_video_id
    ]
    moves = compute_reorder_moves(current_set_ids, target_set_ids)
    if moves:
        yt.edit_playlist(playlist_id, sortOrder=PlaylistSortOrder.MANUAL)
        _apply_reorder(yt, playlist_id, moves)

    return PlaylistSyncReport(
        playlist_name=playlist.name,
        playlist_id=playlist_id,
        total_spotify=len(playlist.tracks),
        matched=len(desired_video_ids),
        added=len(missing_video_ids),
        moved=len(moves),
        unmatched=unmatched,
    )


def sync_all_playlists(
    auth_path: Path,
    cache_dir: Path,
    playlist_paths: list[Path],
    privacy: str = "PRIVATE",
    reverse: bool = False,
    dry_run: bool = False,
    rebuild: bool = False,
) -> list[PlaylistSyncReport]:
    yt = YTMusic(str(auth_path))
    library_index = _index_library_playlists(yt)
    reports: list[PlaylistSyncReport] = []
    for path in playlist_paths:
        print(f"Syncing {path.stem} ({path.name})...", flush=True)
        report = sync_playlist_file(
            yt=yt,
            playlist_path=path,
            cache_dir=cache_dir,
            library_index=library_index,
            privacy=privacy,
            reverse=reverse,
            dry_run=dry_run,
            rebuild=rebuild,
        )
        print(
            f"  total={report.total_spotify} matched={report.matched} "
            f"added={report.added} moved={report.moved} unmatched={len(report.unmatched)}",
            flush=True,
        )
        reports.append(report)
    return reports
