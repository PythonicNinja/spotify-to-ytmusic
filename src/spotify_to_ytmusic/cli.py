"""Command-line interface for spotify-to-ytmusic."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from ytmusicapi import YTMusic

from spotify_to_ytmusic.auth import save_browser_auth
from spotify_to_ytmusic.playlists import discover_playlist_files, load_playlist_file
from spotify_to_ytmusic.sync import sync_all_playlists

DEFAULT_PLAYLISTS_DIR = Path("playlists")
DEFAULT_CACHE_DIR = Path("cache")
DEFAULT_AUTH_PATH = Path("browser.json")


def _read_clipboard() -> str:
    result = subprocess.run(["pbpaste"], capture_output=True, text=True, check=True)
    return result.stdout


def _cmd_auth(args: argparse.Namespace) -> int:
    if args.file:
        raw_input = Path(args.file).read_text(encoding="utf-8")
    elif args.clipboard:
        raw_input = _read_clipboard()
    elif not sys.stdin.isatty():
        raw_input = sys.stdin.read()
    else:
        print("Paste YouTube Music Copy-as-cURL or request headers, then press Ctrl-D:")
        raw_input = sys.stdin.read()

    auth_path = Path(args.output)
    save_browser_auth(raw_input, auth_path)
    yt = YTMusic(str(auth_path))
    playlists = yt.get_library_playlists(limit=5) or []
    print(f"Saved {auth_path} and verified auth ({len(playlists)} library playlists sampled).")
    return 0


def _cmd_check(args: argparse.Namespace) -> int:
    playlists_dir = Path(args.playlists_dir)
    files = discover_playlist_files(playlists_dir, only_name=args.playlist)
    if not files:
        print(f"No Exportify .csv files found in {playlists_dir}.", file=sys.stderr)
        return 1

    for path in files:
        pl = load_playlist_file(path, reverse=args.reverse)
        print(f"{pl.name} ({path.name}): {len(pl.tracks)} unique tracks")
        if pl.tracks:
            first = pl.tracks[0]
            last = pl.tracks[-1]
            print(f"  top:    {first.added_at or '-'} | {first.title} - {first.primary_artist}")
            print(f"  bottom: {last.added_at or '-'} | {last.title} - {last.primary_artist}")
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    auth_path = Path(args.auth)
    if not auth_path.exists():
        print(f"Missing {auth_path}. Run `make step1` first.", file=sys.stderr)
        return 1

    playlists_dir = Path(args.playlists_dir)
    playlist_paths = discover_playlist_files(playlists_dir, only_name=args.playlist)
    if not playlist_paths:
        print(f"No Exportify .csv files found in {playlists_dir}.", file=sys.stderr)
        return 1

    cache_dir = Path(args.cache_dir)
    reports = sync_all_playlists(
        auth_path=auth_path,
        cache_dir=cache_dir,
        playlist_paths=playlist_paths,
        privacy=args.privacy,
        reverse=args.reverse,
        dry_run=args.dry_run,
        rebuild=args.rebuild,
    )

    unmatched = [item.model_dump() for report in reports for item in report.unmatched]
    if unmatched:
        cache_dir.mkdir(parents=True, exist_ok=True)
        unmatched_path = cache_dir / "unmatched.json"
        unmatched_path.write_text(
            json.dumps(unmatched, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Wrote {len(unmatched)} unmatched tracks to {unmatched_path}")

    mode = "DRY RUN" if args.dry_run else "DONE"
    print(f"[{mode}] Processed {len(reports)} playlist(s).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="s2yt",
        description="Sync Spotify Exportify CSV playlists to YouTube Music preserving order.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_auth = sub.add_parser("auth", help="Create browser.json from DevTools cURL or headers.")
    p_auth.add_argument("--file", help="Read headers or cURL from a file instead of stdin.")
    p_auth.add_argument("--clipboard", action="store_true", help="Read cURL/headers via pbpaste.")
    p_auth.add_argument("--output", default=str(DEFAULT_AUTH_PATH), help="Output auth JSON path.")
    p_auth.set_defaults(func=_cmd_auth)

    p_check = sub.add_parser("check", help="Validate Exportify CSV playlists and preview order.")
    p_check.add_argument("--playlist", help="Check only one playlist by name.")
    p_check.add_argument("--playlists-dir", default=str(DEFAULT_PLAYLISTS_DIR))
    p_check.add_argument("--reverse", action="store_true", help="Preview oldest-first order.")
    p_check.set_defaults(func=_cmd_check)

    p_sync = sub.add_parser("sync", help="Sync Exportify CSV playlists to YouTube Music.")
    p_sync.add_argument("--playlist", help="Sync only one playlist by name.")
    p_sync.add_argument("--playlists-dir", default=str(DEFAULT_PLAYLISTS_DIR))
    p_sync.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    p_sync.add_argument("--auth", default=str(DEFAULT_AUTH_PATH))
    p_sync.add_argument("--privacy", choices=["PRIVATE", "UNLISTED", "PUBLIC"], default="PRIVATE")
    p_sync.add_argument("--reverse", action="store_true", help="Order oldest-first instead.")
    p_sync.add_argument(
        "--rebuild",
        action="store_true",
        help="Clear existing playlist tracks and re-add all matched songs in exact order.",
    )
    p_sync.add_argument("--dry-run", action="store_true", help="Match and plan without writing.")
    p_sync.set_defaults(func=_cmd_sync)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
