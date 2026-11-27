"""Minimal move calculation to reorder a YouTube Music playlist to match target order."""

from __future__ import annotations

from bisect import bisect_left


def longest_increasing_subsequence(values: list[int]) -> set[int]:
    if not values:
        return set()

    tails: list[int] = []
    tail_indices: list[int] = []
    prev_index = [-1] * len(values)

    for idx, value in enumerate(values):
        pos = bisect_left(tails, value)
        if pos == len(tails):
            tails.append(value)
            tail_indices.append(idx)
        else:
            tails[pos] = value
            tail_indices[pos] = idx
        if pos > 0:
            prev_index[idx] = tail_indices[pos - 1]

    lis_values: set[int] = set()
    cursor = tail_indices[-1]
    while cursor != -1:
        lis_values.add(values[cursor])
        cursor = prev_index[cursor]
    return lis_values


def compute_reorder_moves(
    current_ids: list[str],
    target_ids: list[str],
) -> list[tuple[str, str | None]]:
    """Return minimal (item_id, before_item_id | None) moves so target_ids appear in exact order.

    None as the second tuple element means move item_id to the end of the playlist.
    """
    present = set(current_ids)
    ordered_target = [item_id for item_id in target_ids if item_id in present]
    if len(ordered_target) <= 1:
        return []

    rank_by_id = {item_id: rank for rank, item_id in enumerate(ordered_target)}
    current_ranks = [rank_by_id[item_id] for item_id in current_ids if item_id in rank_by_id]
    fixed_ranks = longest_increasing_subsequence(current_ranks)

    moves: list[tuple[str, str | None]] = []
    last_idx = len(ordered_target) - 1
    for idx in range(last_idx, -1, -1):
        if idx in fixed_ranks:
            continue
        item_id = ordered_target[idx]
        successor_id = None if idx == last_idx else ordered_target[idx + 1]
        moves.append((item_id, successor_id))
    return moves


def apply_moves(current_ids: list[str], moves: list[tuple[str, str | None]]) -> list[str]:
    result = list(current_ids)
    for item_id, successor_id in moves:
        result.remove(item_id)
        if successor_id is None:
            result.append(item_id)
        else:
            insert_at = result.index(successor_id)
            result.insert(insert_at, item_id)
    return result
