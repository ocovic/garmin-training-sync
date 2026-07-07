"""
garmin_cache.py - Local disk cache for the day-by-day Garmin "batch" fetchers
(fetch_sleep_batch, fetch_hrv_batch, fetch_daily_stats_batch in analytics.py).

Those functions each make one Garmin API call per day requested, every time
they're called - reloading the same 30/60/90 days repeatedly is what triggers
Garmin's rate limiting (HTTP 429). This module wraps them so that only the
date range NOT already cached locally is actually requested from Garmin.

The wrapped functions themselves are never modified - cached_batch_fetch()
just decides how many days to ask them for.
"""
import json
import os
from datetime import datetime, timedelta

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".garmin_cache")


def _paths(name: str):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return (
        os.path.join(CACHE_DIR, f"{name}.pkl"),
        os.path.join(CACHE_DIR, f"{name}.meta.json"),
    )


def _load(name: str):
    data_path, meta_path = _paths(name)
    df = pd.read_pickle(data_path) if os.path.exists(data_path) else pd.DataFrame()

    coverage_start = coverage_end = None
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        coverage_start = datetime.strptime(meta["coverage_start"], "%Y-%m-%d").date()
        coverage_end = datetime.strptime(meta["coverage_end"], "%Y-%m-%d").date()

    return df, coverage_start, coverage_end


def _save(name: str, df: pd.DataFrame, coverage_start, coverage_end):
    data_path, meta_path = _paths(name)
    df.to_pickle(data_path)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "coverage_start": coverage_start.isoformat(),
                "coverage_end": coverage_end.isoformat(),
            },
            f,
        )


def _upsert(cached_df: pd.DataFrame, fresh_df: pd.DataFrame) -> pd.DataFrame:
    if fresh_df.empty:
        return cached_df
    if cached_df.empty:
        return fresh_df.sort_values("date").reset_index(drop=True)
    combined = pd.concat([cached_df, fresh_df], ignore_index=True)
    combined = combined.drop_duplicates(subset="date", keep="last")
    return combined.sort_values("date").reset_index(drop=True)


def cached_batch_fetch(name: str, fetch_fn, client, days: int) -> pd.DataFrame:
    """Return the same DataFrame fetch_fn(client, days) would, but only calls
    Garmin for the portion of the date range that isn't already cached locally.

    name: cache namespace, e.g. "sleep", "hrv", "stats".
    fetch_fn: one of fetch_sleep_batch / fetch_hrv_batch / fetch_daily_stats_batch
              (any function with the same (client, days) -> DataFrame[date, ...] shape).
    """
    today = datetime.now().date()
    required_start = today - timedelta(days=days - 1)

    cached_df, coverage_start, coverage_end = _load(name)

    need_full_refetch = coverage_start is None or required_start < coverage_start
    need_tail_refresh = not need_full_refetch and coverage_end < today

    if need_full_refetch:
        fresh = fetch_fn(client, days)
        cached_df = _upsert(cached_df, fresh)
        coverage_start = required_start
        coverage_end = today
        _save(name, cached_df, coverage_start, coverage_end)
    elif need_tail_refresh:
        # +2-day buffer: re-check the last couple of already-cached days too,
        # in case data synced late (e.g. watch synced a day after the fact).
        gap_days = (today - coverage_end).days + 2
        fresh = fetch_fn(client, gap_days)
        cached_df = _upsert(cached_df, fresh)
        coverage_end = today
        _save(name, cached_df, coverage_start, coverage_end)

    if cached_df.empty:
        return cached_df

    return (
        cached_df[(cached_df["date"] >= required_start) & (cached_df["date"] <= today)]
        .sort_values("date")
        .reset_index(drop=True)
    )
