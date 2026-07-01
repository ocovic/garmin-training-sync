"""
analytics.py - Training load analysis and recovery metrics from Garmin Connect
"""
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd


# ── Activities & PMC ─────────────────────────────────────────────────────────

def fetch_activities(
    client,
    days: int = 90,
    start_date=None,
    end_date=None,
    sport_types: list = None,
) -> pd.DataFrame:
    """Fetch completed activities from Garmin Connect with optional date range and sport filter."""
    today = datetime.now().date()
    if end_date is None:
        end_date = today
    if start_date is None:
        start_date = today - timedelta(days=days)

    if hasattr(client, "get_activities_by_date"):
        raw = client.get_activities_by_date(
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d"),
        )
    else:
        limit = min(max((end_date - start_date).days * 3, 100), 1000)
        raw = client.get_activities(0, limit)

    records = []
    for act in raw:
        start_str = act.get("startTimeLocal", "")
        try:
            start = datetime.strptime(start_str[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            continue

        act_date = start.date()
        if act_date < start_date or act_date > end_date:
            continue

        sport = (act.get("activityType") or {}).get("typeKey", "unknown")

        if sport_types and sport not in sport_types:
            continue

        records.append({
            "date": act_date,
            "datetime": start,
            "activity_id": act.get("activityId"),
            "name": act.get("activityName", ""),
            "sport": sport,
            "duration_sec": float(act.get("duration") or 0),
            "distance_m": float(act.get("distance") or 0),
            "avg_hr": act.get("averageHR"),
            "max_hr": act.get("maxHR"),
            "avg_speed_mps": float(act.get("averageSpeed") or 0),
            "elevation_gain": float(act.get("elevationGain") or 0),
            "calories": float(act.get("calories") or 0),
        })

    _EMPTY_COLS = [
        "date", "datetime", "activity_id", "name", "sport",
        "duration_sec", "distance_m", "avg_hr", "max_hr",
        "avg_speed_mps", "elevation_gain", "calories",
        "distance_km", "duration_min", "avg_pace_minkm",
    ]

    if not records:
        return pd.DataFrame(columns=_EMPTY_COLS)

    df = pd.DataFrame(records)
    df["distance_km"] = df["distance_m"] / 1000
    df["duration_min"] = df["duration_sec"] / 60
    df["avg_pace_minkm"] = df.apply(
        lambda r: (1000 / r["avg_speed_mps"]) / 60
        if (r["avg_speed_mps"] and r["avg_speed_mps"] > 0) else None,
        axis=1,
    )
    return df


def _tss_from_hr(duration_sec: float, avg_hr: Optional[float],
                 threshold_hr: float) -> float:
    """HR-based TSS: (duration × IF²) / 3600 × 100."""
    if duration_sec <= 0:
        return 0.0
    if not avg_hr or avg_hr <= 0:
        return round((duration_sec / 3600) * 60, 1)  # moderate effort default
    intensity_factor = avg_hr / threshold_hr
    return round((duration_sec * intensity_factor ** 2) / 3600 * 100, 1)


def build_pmc(
    activities_df: pd.DataFrame,
    threshold_hr: float = 165,
    warmup_days: int = 60,
) -> pd.DataFrame:
    """
    Build Performance Management Chart: CTL (fitness), ATL (fatigue), TSB (form).

    warmup_days: extra historical days to warm up CTL/ATL before the display window.
    Returns DataFrame with columns: date, tss, ctl, atl, tsb.
    """
    today = datetime.now().date()

    if activities_df.empty:
        return pd.DataFrame(columns=["date", "tss", "ctl", "atl", "tsb"])

    df = activities_df.copy()
    df["tss"] = df.apply(
        lambda r: _tss_from_hr(r["duration_sec"], r["avg_hr"], threshold_hr), axis=1
    )

    daily_tss = df.groupby("date")["tss"].sum()

    actual_start = df["date"].min()
    warmup_start = actual_start - timedelta(days=warmup_days)
    all_dates = [
        (warmup_start + timedelta(days=i))
        for i in range((today - warmup_start).days + 1)
    ]
    daily_tss = daily_tss.reindex(all_dates, fill_value=0.0)

    ctl, atl = 0.0, 0.0
    records = []
    for date, tss in daily_tss.items():
        ctl = ctl + (tss - ctl) / 42
        atl = atl + (tss - atl) / 7
        records.append({
            "date": date,
            "tss": round(tss, 1),
            "ctl": round(ctl, 1),
            "atl": round(atl, 1),
            "tsb": round(ctl - atl, 1),
        })

    full = pd.DataFrame(records)
    return full[full["date"] >= actual_start].reset_index(drop=True)


def weekly_summary(activities_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate completed activities by ISO week."""
    if activities_df.empty:
        return pd.DataFrame()

    df = activities_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["week_start"] = df["date"].dt.to_period("W").apply(lambda p: p.start_time.date())

    summary = df.groupby("week_start").agg(
        sessions=("activity_id", "count"),
        total_km=("distance_km", "sum"),
        total_min=("duration_min", "sum"),
        elevation=("elevation_gain", "sum"),
        avg_hr=("avg_hr", "mean"),
    ).round(1).reset_index()

    return summary.sort_values("week_start")


# ── Sleep ─────────────────────────────────────────────────────────────────────

def fetch_sleep_batch(client, days: int = 30) -> pd.DataFrame:
    """Fetch sleep data for the last N days (one API call per day)."""
    records = []
    today = datetime.now().date()

    for i in range(days):
        date = today - timedelta(days=i)
        try:
            data = client.get_sleep_data(date.strftime("%Y-%m-%d"))
            dto = (data or {}).get("dailySleepDTO") or {}
            total_sec = dto.get("sleepTimeSeconds") or 0
            if not dto or total_sec == 0:
                continue

            # Sleep score structure varies by device/firmware
            sleep_score = None
            scores = dto.get("sleepScores") or {}
            if isinstance(scores, dict):
                overall = scores.get("overall") or {}
                sleep_score = overall.get("value") if isinstance(overall, dict) else overall
            elif isinstance(scores, (int, float)):
                sleep_score = scores

            records.append({
                "date": date,
                "total_hours": round(total_sec / 3600, 2),
                "deep_hours": round((dto.get("deepSleepSeconds") or 0) / 3600, 2),
                "light_hours": round((dto.get("lightSleepSeconds") or 0) / 3600, 2),
                "rem_hours": round((dto.get("remSleepSeconds") or 0) / 3600, 2),
                "awake_min": round((dto.get("awakeSleepSeconds") or 0) / 60, 1),
                "sleep_score": sleep_score,
                "resting_hr": dto.get("restingHeartRate"),
                "avg_spo2": dto.get("averageSpO2Value"),
            })
        except Exception:
            continue

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


# ── HRV ───────────────────────────────────────────────────────────────────────

def fetch_hrv_batch(client, days: int = 30) -> pd.DataFrame:
    """Fetch HRV (Heart Rate Variability) data for the last N days."""
    records = []
    today = datetime.now().date()

    for i in range(days):
        date = today - timedelta(days=i)
        try:
            data = client.get_hrv_data(date.strftime("%Y-%m-%d"))
            summary = (data or {}).get("hrvSummary") or {}
            if not summary:
                continue

            records.append({
                "date": date,
                "hrv_last_night": summary.get("lastNight"),
                "hrv_weekly_avg": summary.get("weeklyAvg"),
                "hrv_5min_high": summary.get("lastNight5MinHigh"),
                "hrv_baseline_low": summary.get("baselineLowUpper"),
                "hrv_baseline_high": summary.get("baselineBalancedUpper"),
                "hrv_status": summary.get("hrvCondition"),
            })
        except Exception:
            continue

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


# ── Daily wellness stats ──────────────────────────────────────────────────────

def fetch_daily_stats_batch(client, days: int = 30) -> pd.DataFrame:
    """Fetch daily wellness stats: resting HR, steps, stress, body battery."""
    today = datetime.now().date()

    # Body battery as a range query (more efficient than per-day)
    bb_by_date: dict = {}
    try:
        start_str = (today - timedelta(days=days)).strftime("%Y-%m-%d")
        end_str = today.strftime("%Y-%m-%d")
        bb_raw = client.get_body_battery(start_str, end_str)
        if isinstance(bb_raw, list):
            for entry in bb_raw:
                if not isinstance(entry, dict):
                    continue
                d = entry.get("date") or (entry.get("startTimestampLocal") or "")[:10]
                stat_list = entry.get("bodyBatteryStatList") or []
                if stat_list and isinstance(stat_list[0], dict):
                    bb_by_date[d] = {
                        "bb_high": stat_list[0].get("high"),
                        "bb_low": stat_list[0].get("low"),
                    }
                elif isinstance(entry.get("charged"), (int, float)):
                    bb_by_date[d] = {
                        "bb_high": entry.get("charged"),
                        "bb_low": entry.get("drained"),
                    }
    except Exception:
        pass

    records = []
    for i in range(days):
        date = today - timedelta(days=i)
        date_str = date.strftime("%Y-%m-%d")
        try:
            stats = client.get_stats(date_str) or {}
            bb = bb_by_date.get(date_str, {})
            records.append({
                "date": date,
                "resting_hr": stats.get("restingHeartRate"),
                "steps": stats.get("totalSteps"),
                "avg_stress": stats.get("averageStressLevel"),
                "active_calories": stats.get("activeKilocalories"),
                "bb_high": bb.get("bb_high"),
                "bb_low": bb.get("bb_low"),
            })
        except Exception:
            continue

    if not records:
        return pd.DataFrame()

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


# ── Conflict detection ────────────────────────────────────────────────────────

def get_conflicts(client, workouts: list) -> list:
    """
    Return list of existing calendar entries on the planned workout dates.
    Each item: {date, planned, existing, is_exact_duplicate}.
    """
    months: dict = {}
    for w in workouts:
        year, month, _ = map(int, w["date"].split("-"))
        months.setdefault((year, month), []).append(w)

    conflicts = []
    for (year, month), month_workouts in months.items():
        try:
            response = client.get_scheduled_workouts(year, month)
            calendar_items = response.get("calendarItems", [])
        except Exception:
            continue

        by_date: dict = {}
        for item in calendar_items:
            if item.get("itemType") != "workout":
                continue
            d = item.get("date", "")
            by_date.setdefault(d, []).append({
                "title": item.get("title", ""),
                "workout_id": item.get("workoutId"),
                "schedule_id": item.get("id"),
            })

        for w in month_workouts:
            for existing in by_date.get(w["date"], []):
                conflicts.append({
                    "date": w["date"],
                    "planned": w["name"],
                    "existing": existing["title"],
                    "is_exact_duplicate": existing["title"] == w["name"],
                    "workout_id": existing["workout_id"],
                    "schedule_id": existing["schedule_id"],
                })

    return conflicts
