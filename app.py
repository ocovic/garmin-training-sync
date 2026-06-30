import json
from datetime import datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from garminconnect import Garmin

from generate_plan import parse_input
from sync_week import (
    build_workout,
    calculate_distance,
    calculate_duration,
    get_sport_config,
    scheduled_exists,
)
from analytics import (
    build_pmc,
    fetch_activities,
    fetch_daily_stats_batch,
    fetch_hrv_batch,
    fetch_sleep_batch,
    get_conflicts,
    weekly_summary,
)


st.set_page_config(page_title="Garmin Training Sync", page_icon="🏃", layout="wide")

st.markdown(
    """
    <style>
        .main-title { font-size: 2.2rem; font-weight: 700; margin-bottom: 0; }
        .subtitle { color: #777; font-size: 1rem; margin-top: 0.2rem; margin-bottom: 1.5rem; }
        .status-ok { color: #16a34a; font-weight: 600; }
        .status-error { color: #dc2626; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── State ──────────────────────────────────────────────────────────────────────

def init_state():
    defaults = {
        "client": None,
        "authenticated": False,
        "plan": None,
        "logs": [],
        "syncing": False,
        "pending_sync": False,
        "force_create": False,
        "sync_status_type": None,
        "sync_status_message": None,
        "auth_status_type": None,
        "auth_status_message": None,
        "conflicts": [],
        "analytics_data": None,
        "threshold_hr": 165,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def log(message: str):
    st.session_state.logs.append(message)


def authenticate(email: str, password: str):
    client = Garmin(email, password)
    client.login()
    st.session_state.client = client
    st.session_state.authenticated = True
    try:
        data = client.get_lactate_threshold()
        hr = data.get("speed_and_heart_rate", {}).get("heartRate")
        if hr and int(hr) > 0:
            st.session_state.threshold_hr = int(hr)
    except Exception:
        pass


def render_alert(status_type: str | None, message: str | None):
    if not status_type or not message:
        return
    if status_type == "success":
        st.success(message)
    elif status_type == "error":
        st.error(message)
    elif status_type == "warning":
        st.warning(message)
    else:
        st.info(message)


# ── Sync preview helpers ────────────────────────────────────────────────────────

def render_step(step: dict, indent: int = 0):
    prefix = " " * indent
    step_type = step["type"]

    if step_type == "repeat":
        st.markdown(f"{prefix}🔁 **Repetir x{step['count']}**")
        for child in step["steps"]:
            render_step(child, indent + 1)
        return

    if step.get("until_lap"):
        condition = "hasta pulsar Lap"
    elif "duration_seconds" in step:
        condition = f"{int(step['duration_seconds']) // 60} min"
    elif "distance_meters" in step:
        condition = f"{step['distance_meters'] / 1000:.2f} km"
    else:
        condition = ""

    target = step.get("target")
    target_text = ""
    if target:
        if target["type"] == "pace":
            target_text = f" · pace {target['min']}-{target['max']}/km"
        elif target["type"] == "heart_rate":
            target_text = f" · FC {target['min']}-{target['max']} ppm"
        elif target["type"] == "hr_zone":
            target_text = f" · Z{target['zone']}"

    icon = {"warmup": "🔴", "run": "🔵", "recovery": "⚫", "cooldown": "🟢"}.get(step_type, "•")
    st.markdown(f"{prefix}{icon} **{step_type}** · {condition}{target_text}")


def render_preview(plan: dict):
    workouts = plan["workouts"]
    for start in range(0, len(workouts), 3):
        cols = st.columns(3, gap="medium")
        for col, workout in zip(cols, workouts[start : start + 3]):
            with col:
                sport = workout.get("sport", "running")
                duration = calculate_duration(workout["steps"])
                distance = calculate_distance(workout["steps"])
                sport_icon = "🏃" if sport == "running" else "🚴"
                with st.container(border=True):
                    st.markdown(f"### {sport_icon} {workout['name']}")
                    st.markdown(
                        f"**Fecha:** {workout['date']}  \n"
                        f"**Deporte:** {sport}  \n"
                        f"**Duración:** {duration // 60} min  \n"
                        f"**Distancia:** {distance / 1000:.2f} km"
                    )
                    st.markdown("**Pasos:**")
                    for step in workout["steps"]:
                        render_step(step)


# ── Sync logic ─────────────────────────────────────────────────────────────────

def sync_plan(plan: dict, force: bool = False):
    """
    Upload and schedule workouts to Garmin Connect.
    force=True skips the duplicate-name check and always creates.
    """
    client = st.session_state.client
    if not client:
        raise ValueError("Primero debés autenticarte con Garmin.")

    created_count = 0
    skipped_count = 0

    for item in plan["workouts"]:
        name = item["name"]
        date = item["date"]
        sport = item.get("sport", "running")
        sport_config = get_sport_config(sport)

        log(f"Revisando: {name} / {date}")

        if not force and scheduled_exists(client, name, date):
            skipped_count += 1
            log(f"Saltado: ya existe en calendario → {name}")
            continue

        log(f"Creando workout: {name} [{sport_config['sportTypeKey']}]")
        workout = build_workout(item)

        upload_method = getattr(client, sport_config["upload_method"])
        created = upload_method(workout)
        workout_id = created["workoutId"]

        log(f"Agendando para {date}")
        scheduled = client.schedule_workout(workout_id, date)

        created_count += 1
        log(f"OK workoutId: {workout_id}")
        log(f"OK scheduleId: {scheduled['workoutScheduleId']}")

    return created_count, skipped_count


# ── Dashboard chart helpers ─────────────────────────────────────────────────────

def _pmc_chart(pmc_df: pd.DataFrame):
    if pmc_df.empty:
        st.info("No se encontraron actividades en el período seleccionado.")
        return

    df = pmc_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    tss_bars = (
        alt.Chart(df)
        .mark_bar(opacity=0.25, color="#94a3b8")
        .encode(
            x=alt.X("date:T", axis=alt.Axis(format="%d %b", title=None)),
            y=alt.Y("tss:Q", title="TSS", axis=alt.Axis(grid=False)),
            tooltip=[
                alt.Tooltip("date:T", format="%d/%m/%Y"),
                alt.Tooltip("tss:Q", format=".0f", title="TSS"),
            ],
        )
    )

    melted = df.melt(id_vars="date", value_vars=["ctl", "atl", "tsb"])
    LABELS = {"ctl": "CTL (Forma)", "atl": "ATL (Fatiga)", "tsb": "TSB (Balance)"}
    COLORS = {"ctl": "#3b82f6", "atl": "#ef4444", "tsb": "#22c55e"}
    melted["label"] = melted["variable"].map(LABELS)

    lines = (
        alt.Chart(melted)
        .mark_line(strokeWidth=2.5)
        .encode(
            x=alt.X("date:T", axis=alt.Axis(format="%d %b", title=None)),
            y=alt.Y("value:Q", title="CTL / ATL / TSB"),
            color=alt.Color(
                "label:N",
                scale=alt.Scale(domain=list(LABELS.values()), range=list(COLORS.values())),
                legend=alt.Legend(title="Métrica", orient="right"),
            ),
            tooltip=[
                alt.Tooltip("date:T", format="%d/%m/%Y"),
                "label:N",
                alt.Tooltip("value:Q", format=".1f"),
            ],
        )
    )

    zero_rule = (
        alt.Chart(pd.DataFrame({"y": [0]}))
        .mark_rule(color="#64748b", strokeDash=[4, 4], opacity=0.6)
        .encode(y=alt.Y("y:Q", title=""))
    )

    chart = (
        alt.layer(tss_bars, lines + zero_rule)
        .resolve_scale(y="independent")
        .properties(height=300)
    )
    st.altair_chart(chart, use_container_width=True)


def _weekly_chart(weekly_df: pd.DataFrame):
    if weekly_df.empty:
        st.info("No hay datos de volumen semanal.")
        return

    df = weekly_df.copy()
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["km_label"] = df["total_km"].round(1).astype(str) + " km"

    bars = (
        alt.Chart(df)
        .mark_bar(color="#14b8a6", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("week_start:T", title="Semana", axis=alt.Axis(format="%d %b")),
            y=alt.Y("total_km:Q", title="km"),
            tooltip=[
                alt.Tooltip("week_start:T", format="%d/%m/%Y", title="Semana"),
                alt.Tooltip("total_km:Q", format=".1f", title="km totales"),
                alt.Tooltip("sessions:Q", title="Sesiones"),
                alt.Tooltip("total_min:Q", format=".0f", title="Minutos"),
                alt.Tooltip("elevation:Q", format=".0f", title="Desnivel (m)"),
            ],
        )
        .properties(height=220)
    )

    text = bars.mark_text(dy=-10, color="#0f766e", fontSize=11, fontWeight="bold").encode(
        text="km_label:N"
    )

    st.altair_chart(bars + text, use_container_width=True)


def _sleep_chart(sleep_df: pd.DataFrame):
    if sleep_df.empty:
        st.info("No hay datos de sueño disponibles para el período seleccionado.")
        return

    df = sleep_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    melted = df.melt(
        id_vars="date",
        value_vars=["deep_hours", "rem_hours", "light_hours"],
        var_name="stage",
        value_name="hours",
    )
    STAGE_LABELS = {"deep_hours": "Profundo", "rem_hours": "REM", "light_hours": "Ligero"}
    melted["stage_name"] = melted["stage"].map(STAGE_LABELS)

    bars = (
        alt.Chart(melted)
        .mark_bar()
        .encode(
            x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
            y=alt.Y("hours:Q", title="Horas", stack="zero"),
            color=alt.Color(
                "stage_name:N",
                scale=alt.Scale(
                    domain=["Profundo", "REM", "Ligero"],
                    range=["#1e40af", "#7c3aed", "#93c5fd"],
                ),
                legend=alt.Legend(title="Fase", orient="right"),
            ),
            order=alt.Order("stage:N", sort="ascending"),
            tooltip=[
                alt.Tooltip("date:T", format="%d/%m/%Y"),
                "stage_name:N",
                alt.Tooltip("hours:Q", format=".1f", title="Horas"),
            ],
        )
        .properties(height=220)
    )

    st.altair_chart(bars, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Sueño total promedio (7d)", f"{df['total_hours'].tail(7).mean():.1f}h")
    if df["sleep_score"].notna().any():
        c2.metric("Score de sueño (7d)", f"{df['sleep_score'].tail(7).mean():.0f}/100")
    if df["avg_spo2"].notna().any():
        c3.metric("SpO₂ promedio (7d)", f"{df['avg_spo2'].tail(7).mean():.1f}%")


def _recovery_chart(hrv_df: pd.DataFrame, stats_df: pd.DataFrame):
    has_hrv = not hrv_df.empty and hrv_df["hrv_last_night"].notna().any()
    has_stats = not stats_df.empty

    if not has_hrv and not has_stats:
        st.info("No hay datos de recuperación disponibles para el período seleccionado.")
        return

    if has_hrv:
        st.markdown("**HRV — Variabilidad de frecuencia cardíaca nocturna**")
        hrv = hrv_df.copy()
        hrv["date"] = pd.to_datetime(hrv["date"])
        valid = hrv[hrv["hrv_last_night"].notna()]

        hrv_line = (
            alt.Chart(valid)
            .mark_line(
                color="#22c55e",
                strokeWidth=2,
                point=alt.OverlayMarkDef(color="#22c55e", size=50),
            )
            .encode(
                x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
                y=alt.Y("hrv_last_night:Q", title="HRV (ms)", scale=alt.Scale(zero=False)),
                tooltip=["date:T", alt.Tooltip("hrv_last_night:Q", title="HRV noche (ms)")],
            )
        )

        has_band = hrv["hrv_baseline_low"].notna().any() and hrv["hrv_baseline_high"].notna().any()
        if has_band:
            band_df = hrv[hrv["hrv_baseline_low"].notna() & hrv["hrv_baseline_high"].notna()]
            band = alt.Chart(band_df).mark_area(opacity=0.15, color="#22c55e").encode(
                x="date:T", y="hrv_baseline_low:Q", y2="hrv_baseline_high:Q"
            )
            hrv_chart = (band + hrv_line).properties(height=200)
        else:
            hrv_chart = hrv_line.properties(height=200)

        st.altair_chart(hrv_chart, use_container_width=True)

    if has_stats:
        stats = stats_df.copy()
        stats["date"] = pd.to_datetime(stats["date"])

        col1, col2 = st.columns(2)

        with col1:
            if stats["resting_hr"].notna().any():
                st.markdown("**FC en reposo**")
                hr_valid = stats[stats["resting_hr"].notna()]
                hr_chart = (
                    alt.Chart(hr_valid)
                    .mark_line(
                        color="#ef4444",
                        strokeWidth=2,
                        point=alt.OverlayMarkDef(color="#ef4444", size=40),
                    )
                    .encode(
                        x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
                        y=alt.Y("resting_hr:Q", title="bpm", scale=alt.Scale(zero=False)),
                        tooltip=["date:T", alt.Tooltip("resting_hr:Q", title="FC reposo (bpm)")],
                    )
                    .properties(height=180)
                )
                st.altair_chart(hr_chart, use_container_width=True)

        with col2:
            if stats["bb_high"].notna().any():
                st.markdown("**Body Battery**")
                bb_valid = stats[stats["bb_high"].notna()]
                bb_area = alt.Chart(bb_valid).mark_area(opacity=0.3, color="#f59e0b").encode(
                    x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
                    y=alt.Y("bb_high:Q", title="%"),
                    y2="bb_low:Q",
                    tooltip=[
                        "date:T",
                        alt.Tooltip("bb_high:Q", title="Máx. cargado"),
                        alt.Tooltip("bb_low:Q", title="Mín. descargado"),
                    ],
                )
                bb_line = (
                    alt.Chart(bb_valid)
                    .mark_line(color="#d97706", strokeWidth=1.5)
                    .encode(x="date:T", y="bb_high:Q")
                )
                st.altair_chart(
                    (bb_area + bb_line).properties(height=180), use_container_width=True
                )

        if stats["avg_stress"].notna().any():
            st.markdown("**Nivel de estrés diario**")
            stress_valid = stats[stats["avg_stress"].notna()]
            stress_chart = (
                alt.Chart(stress_valid)
                .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                .encode(
                    x=alt.X("date:T", title=None, axis=alt.Axis(format="%d %b")),
                    y=alt.Y(
                        "avg_stress:Q", title="Nivel (0–100)", scale=alt.Scale(domain=[0, 100])
                    ),
                    color=alt.condition(
                        alt.datum.avg_stress > 50,
                        alt.value("#dc2626"),
                        alt.value("#8b5cf6"),
                    ),
                    tooltip=["date:T", alt.Tooltip("avg_stress:Q", title="Estrés promedio")],
                )
                .properties(height=150)
            )
            st.altair_chart(stress_chart, use_container_width=True)


def _period_comparison_section(activities_df: pd.DataFrame, pmc_df: pd.DataFrame):
    if activities_df.empty:
        return

    today = datetime.now().date()
    df = activities_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    week_start = today - timedelta(days=today.weekday())
    last_week_start = week_start - timedelta(days=7)
    last_week_end = week_start - timedelta(days=1)
    this_month_start = today.replace(day=1)
    prev_month_end = this_month_start - timedelta(days=1)
    last_month_start = prev_month_end.replace(day=1)
    same_day_cutoff = min(last_month_start + timedelta(days=today.day - 1), prev_month_end)

    def _stats(start, end):
        sub = df[(df["date"] >= start) & (df["date"] <= end)]
        return dict(
            km=round(sub["distance_km"].sum(), 1),
            sessions=len(sub),
            avg_hr=sub["avg_hr"].mean() if sub["avg_hr"].notna().any() else None,
            avg_pace=sub["avg_pace_minkm"].mean() if sub["avg_pace_minkm"].notna().any() else None,
        )

    def _tss(start, end):
        if pmc_df is None or pmc_df.empty:
            return None
        p = pmc_df.copy()
        p["date"] = pd.to_datetime(p["date"]).dt.date
        return round(p[(p["date"] >= start) & (p["date"] <= end)]["tss"].sum(), 1)

    def _d(cur, prev, fmt=".1f"):
        if cur is None or prev is None:
            return None
        return f"{'+' if cur >= prev else ''}{cur - prev:{fmt}}"

    tw, lw = _stats(week_start, today), _stats(last_week_start, last_week_end)
    tm, lm = _stats(this_month_start, today), _stats(last_month_start, same_day_cutoff)
    tw_tss, lw_tss = _tss(week_start, today), _tss(last_week_start, last_week_end)
    tm_tss, lm_tss = _tss(this_month_start, today), _tss(last_month_start, same_day_cutoff)

    st.subheader("Comparación de períodos")
    tab_w, tab_m = st.tabs(["Semana actual vs anterior", "Mes actual vs anterior"])

    with tab_w:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("km", f"{tw['km']:.1f}", delta=_d(tw["km"], lw["km"]))
        c2.metric("Sesiones", tw["sessions"], delta=_d(tw["sessions"], lw["sessions"], ".0f"))
        if tw_tss is not None:
            c3.metric("TSS", f"{tw_tss:.0f}", delta=_d(tw_tss, lw_tss, ".0f"))
        if tw["avg_hr"] and lw["avg_hr"]:
            c4.metric("FC media", f"{tw['avg_hr']:.0f} bpm",
                      delta=_d(tw["avg_hr"], lw["avg_hr"], ".0f"), delta_color="inverse")
        if tw["avg_pace"] and lw["avg_pace"]:
            c5.metric("Pace medio", f"{tw['avg_pace']:.2f} min/km",
                      delta=_d(tw["avg_pace"], lw["avg_pace"]), delta_color="inverse")
        if tw_tss and lw_tss and lw_tss > 0 and abs(tw_tss - lw_tss) / lw_tss > 0.3:
            direction = "aumentó" if tw_tss > lw_tss else "bajó"
            pct = abs(tw_tss - lw_tss) / lw_tss * 100
            st.warning(
                f"⚠️ El TSS semanal {direction} un **{pct:.0f}%** respecto a la semana anterior. "
                "Cambios >30% en la carga semanal elevan el riesgo de lesión."
            )

    with tab_m:
        st.caption(f"Comparando días 1–{today.day} de este mes vs los mismos días del mes anterior.")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("km", f"{tm['km']:.1f}", delta=_d(tm["km"], lm["km"]))
        c2.metric("Sesiones", tm["sessions"], delta=_d(tm["sessions"], lm["sessions"], ".0f"))
        if tm_tss is not None:
            c3.metric("TSS", f"{tm_tss:.0f}", delta=_d(tm_tss, lm_tss, ".0f"))
        if tm["avg_hr"] and lm["avg_hr"]:
            c4.metric("FC media", f"{tm['avg_hr']:.0f} bpm",
                      delta=_d(tm["avg_hr"], lm["avg_hr"], ".0f"), delta_color="inverse")
        if tm["avg_pace"] and lm["avg_pace"]:
            c5.metric("Pace medio", f"{tm['avg_pace']:.2f} min/km",
                      delta=_d(tm["avg_pace"], lm["avg_pace"]), delta_color="inverse")


# ── Dashboard layout ───────────────────────────────────────────────────────────

def render_dashboard():
    if not st.session_state.authenticated:
        st.info("Autentícate primero en la pestaña **🏃 Sincronizar**.")
        return

    st.subheader("Configuración del análisis")

    c1, c2, c3 = st.columns(3)
    threshold_hr = c1.number_input(
        "FC umbral anaeróbico (ppm)",
        min_value=130,
        max_value=200,
        value=st.session_state.threshold_hr,
        step=1,
        key="dash_threshold_hr",
        help="Frecuencia cardíaca en umbral de lactato. Se usa para calcular el TSS de cada actividad. Valor traído automáticamente de Garmin si está disponible.",
    )
    _today = datetime.now().date()
    date_range = c2.date_input(
        "Período de actividades",
        value=(_today - timedelta(days=180), _today),
        max_value=_today,
        key="dash_date_range",
        help="Rango de fechas para cargar actividades en el PMC y volumen semanal.",
    )
    recovery_days = c3.slider(
        "Días de sueño / recuperación", 14, 60, 30, step=7, key="dash_recovery_days"
    )

    _SPORT_MAP = {
        "Carrera": ["running", "trail_running", "treadmill_running"],
        "Ciclismo": ["cycling", "road_biking", "mountain_biking", "indoor_cycling"],
        "Natación": ["swimming", "open_water_swimming"],
        "Fuerza": ["strength_training"],
        "Senderismo / Caminata": ["hiking", "walking"],
    }
    selected_sports = st.multiselect(
        "Tipos de actividad (vacío = todas)",
        options=list(_SPORT_MAP.keys()),
        default=[],
        key="dash_sport_types",
        help="Filtra qué deportes se incluyen en el PMC y el volumen semanal.",
    )
    sport_filter = [k for s in selected_sports for k in _SPORT_MAP[s]] if selected_sports else None

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        _span_days = (date_range[1] - date_range[0]).days
    else:
        _span_days = 0

    if _span_days >= 180:
        st.success("🟢 **Calidad del PMC: Excelente** — ≥180 días. El CTL es muy representativo de tu forma real.")
    elif _span_days >= 90:
        st.success("🟢 **Calidad del PMC: Buena** — 90–179 días. CTL confiable para interpretar tu condición.")
    elif _span_days >= 42:
        st.warning("🟡 **Calidad del PMC: Aceptable** — 42–89 días. Para métricas más precisas se recomiendan al menos 90–180 días.")
    else:
        st.error(
            "🔴 **Calidad del PMC: Limitada** — menos de 42 días. "
            "El CTL necesita al menos 42 días para estabilizarse; con este período la forma puede aparecer muy subestimada."
        )

    if st.button("Cargar análisis", type="primary", key="btn_load_analytics"):
        client = st.session_state.client

        if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
            act_start, act_end = date_range[0], date_range[1]
        else:
            act_end = datetime.now().date()
            act_start = act_end - timedelta(days=90)

        with st.spinner("Cargando actividades completadas..."):
            activities_df = fetch_activities(
                client,
                start_date=act_start,
                end_date=act_end,
                sport_types=sport_filter,
            )

        pmc_df = build_pmc(activities_df, threshold_hr=threshold_hr)
        weekly_df = weekly_summary(activities_df)

        with st.spinner(
            f"Cargando sueño y recuperación ({recovery_days} días) — puede tardar unos segundos..."
        ):
            sleep_df = fetch_sleep_batch(client, recovery_days)
            hrv_df = fetch_hrv_batch(client, recovery_days)
            stats_df = fetch_daily_stats_batch(client, recovery_days)

        _pmc_quality = (
            "excelente" if _span_days >= 180
            else "buena" if _span_days >= 90
            else "aceptable" if _span_days >= 42
            else "limitada"
        )
        st.session_state.analytics_data = {
            "activities": activities_df,
            "pmc": pmc_df,
            "weekly": weekly_df,
            "sleep": sleep_df,
            "hrv": hrv_df,
            "stats": stats_df,
            "threshold_hr": threshold_hr,
            "pmc_days": _span_days,
            "pmc_quality": _pmc_quality,
        }

        st.success(
            f"Datos cargados: {len(activities_df)} actividades · "
            f"{len(sleep_df)} noches de sueño · "
            f"{len(hrv_df)} registros HRV."
        )

    data = st.session_state.analytics_data
    if not data:
        st.info("Haz clic en **Cargar análisis** para ver el dashboard.")
        return

    pmc_df = data["pmc"]
    activities_df = data["activities"]
    sleep_df = data["sleep"]
    hrv_df = data["hrv"]
    stats_df = data["stats"]

    # ── Metric cards ──────────────────────────────────────────────────────────
    st.divider()

    r1c1, r1c2, r1c3, r1c4 = st.columns(4)

    if not pmc_df.empty:
        latest = pmc_df.iloc[-1]
        ctl_delta = atl_delta = None
        if len(pmc_df) >= 8:
            wk_ago = pmc_df.iloc[-8]
            ctl_delta = round(latest["ctl"] - wk_ago["ctl"], 1)
            atl_delta = round(latest["atl"] - wk_ago["atl"], 1)

        tsb = latest["tsb"]
        tsb_help = (
            "🟢 Fresco — listo para competir" if tsb > 5
            else "🟡 Óptimo — buen equilibrio carga/frescura" if tsb > -10
            else "🟠 Productivo — zona de adaptación" if tsb > -25
            else "🔴 Fatigado — considera descanso"
        )

        r1c1.metric(
            "CTL — Forma",
            f"{latest['ctl']:.1f}",
            delta=f"{ctl_delta:+.1f}" if ctl_delta is not None else None,
        )
        r1c2.metric(
            "ATL — Fatiga",
            f"{latest['atl']:.1f}",
            delta=f"{atl_delta:+.1f}" if atl_delta is not None else None,
            delta_color="inverse",
        )
        r1c3.metric("TSB — Balance", f"{latest['tsb']:.1f}", help=tsb_help)

    if not activities_df.empty:
        today = datetime.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_km = activities_df[activities_df["date"] >= week_start]["distance_km"].sum()
        r1c4.metric("km esta semana", f"{week_km:.1f} km")

    # Second row: sleep & recovery summary
    row2 = st.columns(4)
    col_idx = 0

    if not sleep_df.empty and col_idx < 4:
        avg_sleep_7d = sleep_df["total_hours"].tail(7).mean()
        row2[col_idx].metric("Sueño promedio (7d)", f"{avg_sleep_7d:.1f}h")
        col_idx += 1

        if sleep_df["sleep_score"].notna().any() and col_idx < 4:
            row2[col_idx].metric(
                "Score sueño (7d)", f"{sleep_df['sleep_score'].tail(7).mean():.0f}/100"
            )
            col_idx += 1

        if sleep_df["resting_hr"].notna().any() and col_idx < 4:
            row2[col_idx].metric(
                "FC reposo (7d)", f"{sleep_df['resting_hr'].tail(7).mean():.0f} bpm"
            )
            col_idx += 1

    if not hrv_df.empty and hrv_df["hrv_last_night"].notna().any() and col_idx < 4:
        row2[col_idx].metric(
            "HRV promedio (7d)", f"{hrv_df['hrv_last_night'].tail(7).mean():.0f} ms"
        )

    # ── Charts ─────────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Carga de Entrenamiento — PMC")

    with st.expander("¿Cómo interpretar el PMC?"):
        st.markdown(
            f"""
- **CTL** (Forma / Fitness): promedio exponencial de 42 días del TSS. Mayor = más capacidad aeróbica acumulada.
- **ATL** (Fatiga): promedio de 7 días. Sube rápido con cargas intensas; refleja fatiga reciente.
- **TSB** (Balance = CTL − ATL): positivo = fresco, −10 a −30 = zona productiva, < −30 = riesgo de sobreentrenamiento.
- **TSS** (barras grises): carga de cada sesión = `(duración_sec × (FC_media / FC_umbral)²) / 3600 × 100`.
- **FC umbral** en uso: **{data['threshold_hr']} ppm**. Ajústala si el TSS parece muy alto o muy bajo.
            """
        )

    _pmc_chart(pmc_df)

    st.divider()
    st.subheader("Volumen Semanal")
    _weekly_chart(data["weekly"])

    st.divider()
    _period_comparison_section(activities_df, pmc_df)

    st.divider()
    st.subheader("Sueño")
    _sleep_chart(sleep_df)

    st.divider()
    st.subheader("Recuperación")
    _recovery_chart(hrv_df, stats_df)


def _activity_detail_charts(cached: dict, sport: str):
    summary_dto = (cached.get("activity") or {}).get("summaryDTO") or {}
    laps_raw = [
        lap for lap in ((cached.get("splits") or {}).get("lapDTOs") or [])
        if (lap.get("duration") or 0) > 30 and (lap.get("distance") or 0) > 100
    ]
    hr_zones_raw = cached.get("hr_zones") or []
    is_running = any(k in sport for k in ("running", "trail", "treadmill"))

    avg_temp = summary_dto.get("averageTemperature")
    if avg_temp is not None:
        if avg_temp >= 28:
            st.warning(
                f"🌡️ Temperatura media: **{avg_temp:.1f}°C** — "
                "El calor puede elevar la FC hasta 10–15 ppm sobre lo normal, "
                "haciendo que el TSS calculado desde FC quede sobreestimado."
            )
        else:
            st.caption(f"🌡️ Temperatura media: {avg_temp:.1f}°C")

    if laps_raw:
        records = []
        for i, lap in enumerate(laps_raw):
            speed = lap.get("averageSpeed") or 0
            records.append({
                "km": i + 1,
                "pace": round((1000 / speed) / 60, 2) if speed > 0 else None,
                "fc": lap.get("averageHR"),
                "cadencia": lap.get("averageRunCadence"),
                "zancada": lap.get("strideLength"),
                "contacto": lap.get("groundContactTime"),
                "oscilacion": lap.get("verticalOscillation"),
            })
        laps_df = pd.DataFrame(records)

        # ── Análisis de ejecución ──────────────────────────────────────────────
        pace_series = laps_df["pace"].dropna()
        n_km = len(pace_series)
        if n_km >= 4:
            pace_vals = pace_series.tolist()
            mid = n_km // 2
            first_half_avg = sum(pace_vals[:mid]) / mid
            second_half_avg = sum(pace_vals[mid:]) / (n_km - mid)
            split_ratio = (second_half_avg - first_half_avg) / first_half_avg * 100

            third = max(1, n_km // 3)
            fade_secs = (sum(pace_vals[-third:]) / third - sum(pace_vals[:third]) / third) * 60

            pace_mean = pace_series.mean()
            pace_cv = (pace_series.std() / pace_mean * 100) if pace_mean > 0 else 0.0

            st.markdown("**Análisis de ejecución**")
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                split_label = "Negative split ✓" if split_ratio < 0 else ("Neutral" if split_ratio < 2 else "Positive split")
                st.metric("Split ratio (1ª vs 2ª mitad)", f"{split_ratio:+.1f}%", delta=split_label, delta_color="off")
            with ec2:
                fade_label = "Fuerte al final ✓" if fade_secs < 0 else ("Estable" if fade_secs < 15 else "Decaimiento notable")
                st.metric(f"Fade (primeros vs últimos {third} km)", f"{fade_secs:+.0f} seg/km", delta=fade_label, delta_color="off")
            with ec3:
                cv_label = "Muy regular ✓" if pace_cv < 2 else ("Regular" if pace_cv < 4 else "Irregular")
                st.metric("Variación de pace (CV)", f"{pace_cv:.1f}%", delta=cv_label, delta_color="off")

            msgs = []
            if split_ratio > 5:
                rec = (second_half_avg - first_half_avg) * 60 * 0.4
                msgs.append(
                    f"Empezaste demasiado rápido: la segunda mitad fue {abs(second_half_avg - first_half_avg) * 60:.0f} seg/km "
                    f"más lenta. Considera salir {rec:.0f} seg/km más conservador la próxima vez."
                )
            elif split_ratio < -2:
                msgs.append("Buen negative split — administraste el esfuerzo de forma progresiva y aceleraste al final.")
            if fade_secs > 20:
                msgs.append(
                    f"Los últimos {third} km fueron {fade_secs:.0f} seg/km más lentos que los primeros. "
                    "Puede indicar mala nutrición/hidratación o salida demasiado rápida."
                )
            if pace_cv > 5:
                msgs.append("Ritmo muy irregular km a km. Mantener el pace más constante mejora la economía de carrera.")
            for m in msgs:
                st.info(m)

        st.markdown("**Splits por kilómetro**")
        sc1, sc2 = st.columns(2)

        with sc1:
            valid = laps_df[laps_df["pace"].notna()]
            if not valid.empty:
                st.altair_chart(
                    alt.Chart(valid)
                    .mark_bar(color="#14b8a6", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("km:O", title="km"),
                        y=alt.Y("pace:Q", title="min/km", scale=alt.Scale(zero=False)),
                        tooltip=[alt.Tooltip("km:O", title="km"), alt.Tooltip("pace:Q", format=".2f", title="min/km")],
                    )
                    .properties(height=220, title="Pace por km"),
                    use_container_width=True,
                )

        with sc2:
            valid = laps_df[laps_df["fc"].notna()]
            if not valid.empty:
                st.altair_chart(
                    alt.Chart(valid)
                    .mark_bar(color="#ef4444", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("km:O", title="km"),
                        y=alt.Y("fc:Q", title="bpm", scale=alt.Scale(zero=False)),
                        tooltip=[alt.Tooltip("km:O", title="km"), alt.Tooltip("fc:Q", format=".0f", title="FC (bpm)")],
                    )
                    .properties(height=220, title="FC media por km"),
                    use_container_width=True,
                )

        eff_df = laps_df[laps_df["pace"].notna() & laps_df["fc"].notna()].copy()
        if len(eff_df) >= 3:
            eff_df["eficiencia"] = (eff_df["pace"] / eff_df["fc"] * 100).round(3)
            st.markdown("**Eficiencia cardíaca por km**")
            st.altair_chart(
                alt.Chart(eff_df)
                .mark_line(point=True, color="#f97316", strokeWidth=2)
                .encode(
                    x=alt.X("km:O", title="km"),
                    y=alt.Y("eficiencia:Q", title="pace/FC ×100", scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip("km:O", title="km"),
                        alt.Tooltip("pace:Q", format=".2f", title="pace (min/km)"),
                        alt.Tooltip("fc:Q", format=".0f", title="FC (bpm)"),
                        alt.Tooltip("eficiencia:Q", format=".3f", title="pace/FC ×100"),
                    ],
                )
                .properties(height=180),
                use_container_width=True,
            )
            st.caption("↑ Si la línea sube durante la carrera significa que necesitás más FC para mantener el mismo ritmo — señal de fatiga acumulada.")

        if is_running and laps_df["cadencia"].notna().any():
            st.markdown("**Dinámica de carrera por km**")
            dyn_specs = [
                ("cadencia", "Cadencia (spm)", "#6366f1"),
                ("zancada", "Zancada (cm)", "#f59e0b"),
                ("contacto", "Contacto suelo (ms)", "#8b5cf6"),
                ("oscilacion", "Oscil. vertical (cm)", "#22c55e"),
            ]
            d1, d2, d3, d4 = st.columns(4)
            for col, (field, label, color) in zip([d1, d2, d3, d4], dyn_specs):
                valid = laps_df[laps_df[field].notna()]
                if valid.empty:
                    continue
                with col:
                    st.altair_chart(
                        alt.Chart(valid)
                        .mark_bar(color=color, cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
                        .encode(
                            x=alt.X("km:O", title=None),
                            y=alt.Y(f"{field}:Q", title=None, scale=alt.Scale(zero=False)),
                            tooltip=[alt.Tooltip("km:O"), alt.Tooltip(f"{field}:Q", format=".1f", title=label)],
                        )
                        .properties(height=150, title=label),
                        use_container_width=True,
                    )

            cad_clean = laps_df["cadencia"].dropna().tolist()
            if len(cad_clean) >= 4:
                cad_first3 = sum(cad_clean[:3]) / 3
                cad_last3 = sum(cad_clean[-3:]) / 3
                cad_drop_pct = (cad_first3 - cad_last3) / cad_first3 * 100
                if cad_drop_pct > 2:
                    st.caption(
                        f"📉 Cadencia bajó {cad_first3 - cad_last3:.0f} spm ({cad_drop_pct:.1f}%) "
                        "en los últimos 3 km — señal de fatiga neuromuscular."
                    )
                elif cad_drop_pct < -1:
                    st.caption(
                        f"📈 Cadencia aumentó {abs(cad_first3 - cad_last3):.0f} spm al final — buena activación en el tramo final."
                    )
                else:
                    st.caption(f"✓ Cadencia estable durante toda la carrera ({cad_drop_pct:+.1f}% variación primeros vs últimos 3 km).")

    zones_with_data = [z for z in hr_zones_raw if (z.get("secsInZone") or 0) > 0]
    if zones_with_data:
        st.markdown("**Distribución en zonas de FC**")
        _ZONE_COLORS = {"Z1": "#93c5fd", "Z2": "#22c55e", "Z3": "#f59e0b", "Z4": "#ef4444", "Z5": "#7c3aed"}
        zones_df = pd.DataFrame([
            {
                "zona": f"Z{z['zoneNumber']} (≥{z['zoneLowBoundary']} bpm)",
                "zkey": f"Z{z['zoneNumber']}",
                "minutos": round(z["secsInZone"] / 60, 1),
            }
            for z in zones_with_data
        ])
        domains = zones_df["zona"].tolist()
        ranges_colors = [_ZONE_COLORS.get(z, "#94a3b8") for z in zones_df["zkey"].tolist()]
        total_min = zones_df["minutos"].sum()

        zc1, zc2 = st.columns([1, 1])
        with zc1:
            st.altair_chart(
                alt.Chart(zones_df)
                .mark_arc(innerRadius=55, outerRadius=105)
                .encode(
                    theta=alt.Theta("minutos:Q"),
                    color=alt.Color("zona:N", scale=alt.Scale(domain=domains, range=ranges_colors), legend=None),
                    tooltip=["zona:N", alt.Tooltip("minutos:Q", format=".1f", title="min")],
                )
                .properties(height=230),
                use_container_width=True,
            )
        with zc2:
            st.markdown("")
            for _, zrow in zones_df.iterrows():
                pct = zrow["minutos"] / total_min * 100 if total_min > 0 else 0
                dot = _ZONE_COLORS.get(zrow["zkey"], "#94a3b8")
                st.markdown(f"**{zrow['zona']}** — {zrow['minutos']:.1f} min · {pct:.0f}%")

    # ── Exportar análisis ──────────────────────────────────────────────────────
    export_data = {
        "resumen": {
            "distancia_km": round((summary_dto.get("distance") or 0) / 1000, 2),
            "duracion_min": round((summary_dto.get("duration") or 0) / 60, 1),
            "fc_media_bpm": summary_dto.get("averageHR"),
            "fc_max_bpm": summary_dto.get("maxHR"),
            "desnivel_m": summary_dto.get("elevationGain"),
            "calorias": summary_dto.get("calories"),
            "temperatura_c": avg_temp,
        },
    }

    if laps_raw:
        export_data["splits_por_km"] = laps_df.to_dict(orient="records")

        eff_ex = laps_df[laps_df["pace"].notna() & laps_df["fc"].notna()].copy()
        if len(eff_ex) >= 3:
            eff_ex["eficiencia"] = (eff_ex["pace"] / eff_ex["fc"] * 100).round(3)
            export_data["eficiencia_cardiaca"] = eff_ex[["km", "pace", "fc", "eficiencia"]].to_dict(orient="records")

        pace_ex = laps_df["pace"].dropna()
        if len(pace_ex) >= 4:
            pv = pace_ex.tolist()
            mid_ex = len(pv) // 2
            fh = sum(pv[:mid_ex]) / mid_ex
            sh = sum(pv[mid_ex:]) / (len(pv) - mid_ex)
            third_ex = max(1, len(pv) // 3)
            export_data["analisis_ejecucion"] = {
                "split_ratio_pct": round((sh - fh) / fh * 100, 2),
                "fade_seg_km": round((sum(pv[-third_ex:]) / third_ex - sum(pv[:third_ex]) / third_ex) * 60, 1),
                "variacion_pace_cv_pct": round(pace_ex.std() / pace_ex.mean() * 100, 2),
                "pace_primera_mitad_minkm": round(fh, 3),
                "pace_segunda_mitad_minkm": round(sh, 3),
            }

        cad_ex = laps_df["cadencia"].dropna().tolist()
        if len(cad_ex) >= 4:
            cf3 = sum(cad_ex[:3]) / 3
            cl3 = sum(cad_ex[-3:]) / 3
            export_data["cadencia"] = {
                "promedio_primeros_3km_spm": round(cf3, 1),
                "promedio_ultimos_3km_spm": round(cl3, 1),
                "decaimiento_pct": round((cf3 - cl3) / cf3 * 100, 2),
            }

    if zones_with_data:
        total_secs = sum(z["secsInZone"] for z in zones_with_data)
        export_data["zonas_fc"] = [
            {
                "zona": f"Z{z['zoneNumber']}",
                "limite_inferior_bpm": z["zoneLowBoundary"],
                "minutos": round(z["secsInZone"] / 60, 1),
                "porcentaje": round(z["secsInZone"] / total_secs * 100, 1) if total_secs else 0,
            }
            for z in zones_with_data
        ]

    st.divider()
    st.download_button(
        label="⬇ Exportar análisis completo (JSON)",
        data=json.dumps(export_data, ensure_ascii=False, indent=2),
        file_name="analisis_actividad.json",
        mime="application/json",
    )


# ── Activities tab ─────────────────────────────────────────────────────────────

def render_activities_tab():
    if not st.session_state.authenticated:
        st.info("Autentícate primero en la pestaña **🏃 Sincronizar**.")
        return

    # ── Fuente de actividades ─────────────────────────────────────────────────
    data = st.session_state.analytics_data
    if data and not data["activities"].empty:
        activities_df = data["activities"]
        st.caption(f"{len(activities_df)} actividades del período cargado en el Dashboard.")
    else:
        st.info("Cargá el Dashboard primero, o seleccioná un período aquí:")
        _today = datetime.now().date()
        col1, col2 = st.columns([3, 1])
        act_range = col1.date_input(
            "Período",
            value=(_today - timedelta(days=180), _today),
            max_value=_today,
            key="act_tab_date_range",
        )
        if col2.button("Cargar", key="btn_act_tab_load", use_container_width=True, type="primary"):
            s, e = (
                (act_range[0], act_range[1])
                if isinstance(act_range, (list, tuple)) and len(act_range) == 2
                else (_today - timedelta(days=180), _today)
            )
            with st.spinner("Cargando actividades..."):
                st.session_state["act_tab_df"] = fetch_activities(
                    st.session_state.client, start_date=s, end_date=e
                )

        activities_df = st.session_state.get("act_tab_df", pd.DataFrame())
        if activities_df.empty:
            return

    # ── Tabla resumen ─────────────────────────────────────────────────────────
    _COLS = {
        "date": "Fecha", "name": "Nombre", "sport": "Deporte",
        "distance_km": "Distancia (km)", "duration_min": "Duración (min)",
        "avg_hr": "FC media", "elevation_gain": "Desnivel (m)", "calories": "Calorías",
    }
    disp = activities_df[list(_COLS.keys())].copy().rename(columns=_COLS)
    disp["Distancia (km)"] = disp["Distancia (km)"].round(2)
    disp["Duración (min)"] = disp["Duración (min)"].round(0)
    disp["Desnivel (m)"] = disp["Desnivel (m)"].round(0)

    st.dataframe(disp, use_container_width=True, hide_index=True)
    st.download_button(
        "⬇ Descargar tabla CSV",
        data=disp.to_csv(index=False).encode("utf-8"),
        file_name="actividades.csv",
        mime="text/csv",
        key="btn_csv_all",
    )

    # ── Detalle de actividad individual ───────────────────────────────────────
    st.divider()
    st.subheader("Detalle de actividad")

    labels = [
        f"{r['date']}  ·  {r['name']}  ({r['sport']})"
        for _, r in activities_df.iterrows()
    ]
    sel_idx = st.selectbox(
        "Seleccionar actividad",
        range(len(labels)),
        format_func=lambda i: labels[i],
        key="act_tab_select",
    )

    row = activities_df.iloc[sel_idx]
    activity_id = int(row["activity_id"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Distancia", f"{row['distance_km']:.2f} km")
    c2.metric("Duración", f"{int(row['duration_min'])} min")
    c3.metric("FC media", f"{int(row['avg_hr'])} bpm" if pd.notna(row["avg_hr"]) else "—")
    c4.metric("Desnivel", f"{row['elevation_gain']:.0f} m")

    detail_key = f"act_detail_{activity_id}"

    if st.button("Cargar datos completos de esta actividad", key="btn_load_detail", type="primary"):
        with st.spinner("Descargando datos de Garmin..."):
            try:
                client = st.session_state.client
                gpx_bytes = None
                try:
                    from garminconnect import Garmin as _G
                    gpx_bytes = client.download_activity(
                        activity_id, dl_fmt=_G.ActivityDownloadFormat.GPX
                    )
                except Exception:
                    pass
                st.session_state[detail_key] = {
                    "summary": row.to_dict(),
                    "activity": client.get_activity(activity_id),
                    "splits": client.get_activity_splits(activity_id),
                    "hr_zones": client.get_activity_hr_in_timezones(activity_id),
                    "gpx": gpx_bytes,
                }
                st.success("Datos cargados.")
            except Exception as e:
                st.error(f"No se pudo cargar el detalle: {e}")

    if st.session_state.get(detail_key):
        cached = st.session_state[detail_key]
        json_str = json.dumps(
            {k: v for k, v in cached.items() if k != "gpx"},
            default=str, indent=2, ensure_ascii=False,
        )
        dl1, dl2 = st.columns(2)
        dl1.download_button(
            "⬇ JSON completo",
            data=json_str.encode("utf-8"),
            file_name=f"actividad_{activity_id}.json",
            mime="application/json",
            use_container_width=True,
            key=f"btn_json_{activity_id}",
        )
        if cached.get("gpx"):
            dl2.download_button(
                "⬇ GPX",
                data=cached["gpx"],
                file_name=f"actividad_{activity_id}.gpx",
                mime="application/gpx+xml",
                use_container_width=True,
                key=f"btn_gpx_{activity_id}",
            )

        st.divider()
        _activity_detail_charts(cached, str(row.get("sport", "")))


# ── App layout ─────────────────────────────────────────────────────────────────

init_state()

st.markdown('<p class="main-title">Garmin Training Sync</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">Convierte sesiones en lenguaje natural y sincronízalas con Garmin Connect.</p>',
    unsafe_allow_html=True,
)

tab_sync, tab_dash, tab_acts = st.tabs(["🏃 Sincronizar", "📊 Dashboard", "📋 Actividades"])


with tab_sync:
    left, right = st.columns([0.34, 0.66], gap="large")

    with left:
        st.subheader("Autenticación Garmin")

        email = st.text_input("Email Garmin", key="auth_email")
        password = st.text_input("Password Garmin", type="password", key="auth_password")

        if st.button("Autenticar", use_container_width=True, disabled=st.session_state.syncing):
            try:
                with st.spinner("Autenticando con Garmin..."):
                    authenticate(email, password)
                st.session_state.auth_status_type = "success"
                st.session_state.auth_status_message = "Autenticación correcta."
                log("Autenticación correcta.")
            except Exception as e:
                st.session_state.auth_status_type = "error"
                st.session_state.auth_status_message = "No se pudo autenticar."
                log(f"Error autenticando: {e}")

        render_alert(st.session_state.auth_status_type, st.session_state.auth_status_message)

        if st.session_state.authenticated:
            st.markdown('<p class="status-ok">● Conectado</p>', unsafe_allow_html=True)
        else:
            st.markdown('<p class="status-error">● No autenticado</p>', unsafe_allow_html=True)

        st.divider()
        st.subheader("Acciones")

        generate_clicked = st.button(
            "Generar Preview", use_container_width=True, disabled=st.session_state.syncing
        )

        sync_label = "⏳ Sincronizando..." if st.session_state.syncing else "Sincronizar"
        sync_clicked = st.button(
            sync_label,
            use_container_width=True,
            type="primary",
            disabled=st.session_state.syncing,
        )

        clear_clicked = st.button(
            "Limpiar", use_container_width=True, disabled=st.session_state.syncing
        )

        if clear_clicked:
            st.session_state.session_text = ""
            st.session_state.plan = None
            st.session_state.conflicts = []
            st.rerun()

        # Conflict action selector — only shown when conflicts were detected
        if st.session_state.conflicts:
            st.divider()
            conflict_action = st.radio(
                "Acción para conflictos:",
                ["Saltar duplicados exactos", "Crear igualmente"],
                key="conflict_action_radio",
                help=(
                    "**Saltar duplicados**: omite un workout si ya hay uno con el mismo nombre "
                    "en esa fecha.\n\n"
                    "**Crear igualmente**: sube el workout aunque ya exista algo en ese día "
                    "(puede crear duplicados en el calendario)."
                ),
            )
            st.session_state.force_create = conflict_action == "Crear igualmente"

        render_alert(st.session_state.sync_status_type, st.session_state.sync_status_message)

        if sync_clicked:
            st.session_state.pending_sync = True
            st.session_state.syncing = True
            st.session_state.sync_status_type = "info"
            st.session_state.sync_status_message = "Sincronizando con Garmin Connect..."
            st.rerun()

    with right:
        st.subheader("Sesiones de entrenamiento")

        placeholder_text = """Fecha: 2026-07-01
Nombre: Mié01-Jul - Umbral

Sesión:
15 min calentamiento Z1
4 x 1 km @4:10-4:25 rec 2 min
10 min enfriamiento Z1

---
Fecha: 2026-07-04
Nombre: Sáb04-Jul - Easy

Sesión:
45 min fácil Z2"""

        session_text = st.text_area(
            "Sesiones",
            key="session_text",
            placeholder=placeholder_text,
            height=320,
            label_visibility="collapsed",
            disabled=st.session_state.syncing,
        )

        if generate_clicked:
            try:
                plan = parse_input(session_text)
                warnings = plan.pop("warnings", [])
                st.session_state.plan = plan
                st.session_state.conflicts = []

                st.success(f"Preview generado. Workouts: {len(plan['workouts'])}")
                log(f"Preview generado. Workouts: {len(plan['workouts'])}")

                for w in warnings:
                    st.warning(f"Paso ignorado (falta tiempo o distancia): {w}")
                    log(f"Paso ignorado: {w}")

                # Conflict check against the live Garmin calendar
                if st.session_state.authenticated:
                    with st.spinner("Verificando el calendario de Garmin..."):
                        try:
                            conflicts = get_conflicts(st.session_state.client, plan["workouts"])
                            st.session_state.conflicts = conflicts
                        except Exception:
                            pass  # conflict check is informational — don't block

            except Exception as e:
                st.error("No se pudo generar el preview.")
                log(f"Error generando preview: {e}")

        # Conflict warning + table
        if st.session_state.conflicts:
            n = len(st.session_state.conflicts)
            st.warning(
                f"⚠️ {n} workout(s) ya están agendados en esas fechas. "
                "Revisá la tabla y elegí la acción en el panel izquierdo."
            )
            conflict_df = pd.DataFrame(
                [
                    {
                        "Fecha": c["date"],
                        "Planeado": c["planned"],
                        "Ya agendado": c["existing"],
                    }
                    for c in st.session_state.conflicts
                ]
            )
            st.dataframe(conflict_df, use_container_width=True, hide_index=True)

        # Preview cards
        if st.session_state.plan:
            st.subheader("Preview")
            render_preview(st.session_state.plan)

            json_data = json.dumps(st.session_state.plan, indent=2, ensure_ascii=False)
            st.download_button(
                "Descargar plan_semana.json",
                data=json_data,
                file_name="plan_semana.json",
                mime="application/json",
                use_container_width=True,
                disabled=st.session_state.syncing,
            )

    st.divider()
    st.subheader("Logs")
    st.text_area(
        "Resultados",
        value="\n".join(st.session_state.logs),
        height=220,
        label_visibility="collapsed",
    )


with tab_dash:
    render_dashboard()

with tab_acts:
    render_activities_tab()


# ── Pending sync handler ───────────────────────────────────────────────────────
# Runs at the bottom so it triggers after all widgets have rendered.

if st.session_state.pending_sync:
    try:
        if not st.session_state.plan:
            result = parse_input(session_text)
            result.pop("warnings", [])
            st.session_state.plan = result

        force = st.session_state.get("force_create", False)
        created_count, skipped_count = sync_plan(st.session_state.plan, force=force)

        st.session_state.sync_status_type = "success"
        st.session_state.sync_status_message = (
            f"Sincronización finalizada. "
            f"Creados: {created_count}. Saltados: {skipped_count}."
        )

    except Exception as e:
        st.session_state.sync_status_type = "error"
        st.session_state.sync_status_message = "No se pudo sincronizar."
        log(f"Error sincronizando: {e}")

    finally:
        st.session_state.pending_sync = False
        st.session_state.syncing = False
        st.rerun()
