"""Convert DevTools headers, Copy-as-cURL, or Copy-as-fetch into ytmusicapi browser.json."""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import ytmusicapi

HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*:?$")
PSEUDO_HEADER_RE = re.compile(r"^:[a-z]+:?$")
ANSI_C_QUOTE_RE = re.compile(r"\$'((?:[^'\\]|\\.)*)'")
DEVTOOLS_UI_LABELS = {"raw", "parsed", "view source", "view parsed", "request headers"}


def _strip_ansi_c_quotes(text: str) -> str:
    return ANSI_C_QUOTE_RE.sub(lambda m: "'" + m.group(1).replace("'", "") + "'", text)


def _parse_curl_headers(text: str) -> dict[str, str]:
    unwrapped = text.replace("\\\r\n", " ").replace("\\\n", " ")
    tokens = shlex.split(_strip_ansi_c_quotes(unwrapped))
    headers: dict[str, str] = {}

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token in {"-H", "--header"} and idx + 1 < len(tokens):
            raw = tokens[idx + 1]
            if ":" in raw:
                key, val = raw.split(":", 1)
                headers[key.strip().lower()] = val.strip()
            idx += 2
        elif token in {"-b", "--cookie"} and idx + 1 < len(tokens):
            headers["cookie"] = tokens[idx + 1].strip()
            idx += 2
        else:
            idx += 1
    return headers


def _parse_fetch_headers(text: str) -> dict[str, str]:
    match = re.search(r'"headers"\s*:\s*(\{.*?\})', text, re.S)
    if not match:
        return {}
    raw_obj = json.loads(match.group(1))
    return {str(k).strip().lower(): str(v).strip() for k, v in raw_obj.items()}


def _parse_multiline_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        lower = line.lower()

        if lower.startswith(("get ", "post ", "put ", "options ", "delete ", "head ")):
            idx += 1
            continue
        if PSEUDO_HEADER_RE.match(lower):
            idx += 2
            continue
        if line.startswith(":"):
            idx += 1
            continue

        if ": " in line:
            key, val = line.split(": ", 1)
            if HEADER_NAME_RE.match(key):
                headers[key.strip().lower()] = val.strip()
                idx += 1
                continue

        if ":" in line and not line.endswith(":"):
            key, val = line.split(":", 1)
            if HEADER_NAME_RE.match(key):
                headers[key.strip().lower()] = val.strip()
                idx += 1
                continue

        if (
            lower.rstrip(":") not in DEVTOOLS_UI_LABELS
            and HEADER_NAME_RE.match(line)
            and idx + 1 < len(lines)
            and not lines[idx + 1].startswith(":")
        ):
            headers[lower.rstrip(":")] = lines[idx + 1]
            idx += 2
            continue

        idx += 1

    return headers


def extract_headers(text: str) -> dict[str, str]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.lower().startswith("curl "):
        return _parse_curl_headers(stripped)
    if stripped.startswith("fetch("):
        return _parse_fetch_headers(stripped)
    return _parse_multiline_headers(stripped)


def save_browser_auth(raw_input: str, output_path: Path) -> Path:
    headers = extract_headers(raw_input)
    missing = sorted({"cookie", "x-goog-authuser"} - set(headers))
    if missing:
        found_keys = ", ".join(sorted(headers)[:15]) or "(none)"
        raise ValueError(
            f"Missing required headers: {', '.join(missing)}. "
            f"Parsed header keys: {found_keys}. "
            "Copy a logged-in POST /browse request from music.youtube.com as cURL."
        )

    headers_raw = "\n".join(f"{key}: {val}" for key, val in headers.items())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ytmusicapi.setup(filepath=str(output_path), headers_raw=headers_raw)
    return output_path
