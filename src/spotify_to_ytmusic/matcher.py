"""Match Spotify tracks to YouTube Music video IDs with title/artist/duration scoring."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from ytmusicapi import YTMusic

from spotify_to_ytmusic.models import SpotifyTrack, YTMusicMatch

PARENS_FEAT_RE = re.compile(r"[\(\[].*?(?:feat\.?|ft\.?|with|remaster(?:ed)?).*?[\)\]]", re.I)
NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
EXTRA_CHAR_FOLD = str.maketrans({"ł": "l", "đ": "d", "ø": "o", "ß": "ss"})


def fold_diacritics(text: str) -> str:
    folded = text.lower().translate(EXTRA_CHAR_FOLD)
    decomposed = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


def normalize_text(text: str) -> str:
    cleaned = PARENS_FEAT_RE.sub(" ", fold_diacritics(text))
    cleaned = NON_ALNUM_RE.sub(" ", cleaned)
    return " ".join(cleaned.split())


def parse_duration_seconds(candidate: dict[str, Any]) -> int | None:
    raw_seconds = candidate.get("duration_seconds")
    if isinstance(raw_seconds, int) and raw_seconds > 0:
        return raw_seconds

    duration_str = candidate.get("duration")
    if not isinstance(duration_str, str) or ":" not in duration_str:
        return None
    parts = duration_str.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    total = 0
    for num in nums:
        total = total * 60 + num
    return total if total > 0 else None


def extract_candidate_artists(candidate: dict[str, Any]) -> list[str]:
    artists = candidate.get("artists") or []
    return [a["name"] for a in artists if isinstance(a, dict) and a.get("name")]


def _score_artists(spotify_artists: list[str], cand_artists: list[str], cand_title: str) -> float:
    if not spotify_artists:
        return 0.5
    norm_sp = [normalize_text(a) for a in spotify_artists if normalize_text(a)]
    if not norm_sp:
        return 0.5
    norm_cand = [normalize_text(a) for a in cand_artists if normalize_text(a)]
    norm_title = normalize_text(cand_title)

    best = 0.0
    for sp_artist in norm_sp:
        if sp_artist in norm_title:
            best = max(best, 0.85)
        for cand_artist in norm_cand:
            if sp_artist == cand_artist:
                return 1.0
            if sp_artist in cand_artist or cand_artist in sp_artist:
                best = max(best, 0.9)
            else:
                best = max(best, SequenceMatcher(None, sp_artist, cand_artist).ratio())
    return best


def _score_duration(target_sec: int | None, cand_sec: int | None) -> float:
    if target_sec is None or cand_sec is None:
        return 0.5
    diff = abs(target_sec - cand_sec)
    if diff <= 5:
        return 1.0
    if diff <= 15:
        return 0.75
    if diff <= 30:
        return 0.35
    if diff <= 60:
        return 0.0
    return -0.5


def score_candidate(track: SpotifyTrack, candidate: dict[str, Any]) -> float:
    cand_title = str(candidate.get("title") or "")
    if not cand_title or not candidate.get("videoId"):
        return 0.0

    norm_target_title = normalize_text(track.title)
    norm_cand_title = normalize_text(cand_title)
    title_sim = SequenceMatcher(None, norm_target_title, norm_cand_title).ratio()
    if norm_target_title and norm_target_title in norm_cand_title:
        title_sim = max(title_sim, 0.85)

    cand_artists = extract_candidate_artists(candidate)
    artist_sim = _score_artists(track.artists, cand_artists, cand_title)
    cand_duration = parse_duration_seconds(candidate)
    duration_sim = _score_duration(track.duration_sec, cand_duration)

    score = 0.55 * title_sim + 0.30 * artist_sim + 0.15 * duration_sim
    if candidate.get("resultType") == "song":
        score += 0.05
    return round(min(score, 1.0), 4)


def _pick_best(
    track: SpotifyTrack, candidates: list[dict[str, Any]]
) -> tuple[float, dict[str, Any] | None]:
    best_score = 0.0
    best_cand: dict[str, Any] | None = None
    for cand in candidates:
        if not cand.get("videoId"):
            continue
        score = score_candidate(track, cand)
        if score > best_score:
            best_score = score
            best_cand = cand
    return best_score, best_cand


def find_best_match(
    yt: YTMusic,
    track: SpotifyTrack,
    min_score: float = 0.45,
) -> YTMusicMatch | None:
    song_results = yt.search(track.search_query, filter="songs", limit=5) or []
    best_score, best_cand = _pick_best(track, song_results)

    if best_score < 0.70:
        video_results = yt.search(track.search_query, filter="videos", limit=5) or []
        vid_score, vid_cand = _pick_best(track, video_results)
        if vid_score > best_score:
            best_score, best_cand = vid_score, vid_cand

    if best_cand is None or best_score < min_score:
        return None

    return YTMusicMatch(
        spotify_track_id=track.track_id,
        video_id=str(best_cand["videoId"]),
        title=str(best_cand.get("title") or ""),
        artists=extract_candidate_artists(best_cand),
        duration_sec=parse_duration_seconds(best_cand),
        score=best_score,
    )
