import json
import streamlit as st
from garminconnect import Garmin

from generate_plan import parse_input
from sync_week import (
    build_workout,
    scheduled_exists,
    get_sport_config,
    calculate_duration,
    calculate_distance,
)


st.set_page_config(
    page_title="Garmin Training Sync",
    page_icon="🏃",
    layout="wide",
)


st.markdown(
    """
    <style>
        .main-title {
            font-size: 2.2rem;
            font-weight: 700;
            margin-bottom: 0;
        }
        .subtitle {
            color: #777;
            font-size: 1rem;
            margin-top: 0.2rem;
            margin-bottom: 2rem;
        }
        .status-ok {
            color: #16a34a;
            font-weight: 600;
        }
        .status-error {
            color: #dc2626;
            font-weight: 600;
        }
        .small-muted {
            color: #777;
            font-size: 0.9rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


def init_state():
    if "client" not in st.session_state:
        st.session_state.client = None

    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if "plan" not in st.session_state:
        st.session_state.plan = None

    if "logs" not in st.session_state:
        st.session_state.logs = []


def log(message: str):
    st.session_state.logs.append(message)


def authenticate(email: str, password: str):
    client = Garmin(email, password)
    client.login()

    st.session_state.client = client
    st.session_state.authenticated = True


def render_step(step: dict, indent: int = 0):
    prefix = " " * indent
    step_type = step["type"]

    if step_type == "repeat":
        st.markdown(f"{prefix}🔁 **Repetir x{step['count']}**")
        for child in step["steps"]:
            render_step(child, indent + 1)
        return

    condition = ""
    if step.get("until_lap"):
        condition = "hasta pulsar Lap"
    elif "duration_seconds" in step:
        condition = f"{int(step['duration_seconds']) // 60} min"
    elif "distance_meters" in step:
        condition = f"{step['distance_meters'] / 1000:.2f} km"

    target = step.get("target")
    target_text = ""

    if target:
        if target["type"] == "pace":
            target_text = f" · pace {target['min']}-{target['max']}/km"
        elif target["type"] == "heart_rate":
            target_text = f" · FC {target['min']}-{target['max']} ppm"
        elif target["type"] == "hr_zone":
            target_text = f" · Z{target['zone']}"

    icon = {
        "warmup": "🔴",
        "run": "🔵",
        "recovery": "⚫",
        "cooldown": "🟢",
    }.get(step_type, "•")

    st.markdown(f"{prefix}{icon} **{step_type}** · {condition}{target_text}")


def render_preview(plan: dict):
    for workout in plan["workouts"]:
        sport = workout.get("sport", "running")
        duration = calculate_duration(workout["steps"])
        distance = calculate_distance(workout["steps"])

        with st.container(border=True):
            st.markdown(f"### {workout['name']}")
            st.markdown(
                f"""
                **Fecha:** {workout['date']}  
                **Deporte:** {sport}  
                **Duración estimada:** {duration // 60} min  
                **Distancia estimada:** {distance / 1000:.2f} km
                """
            )

            st.markdown("**Pasos:**")
            for step in workout["steps"]:
                render_step(step)


def sync_plan(plan: dict):
    client = st.session_state.client

    if not client:
        raise ValueError("Primero debés autenticarte con Garmin.")

    for item in plan["workouts"]:
        name = item["name"]
        date = item["date"]
        sport = item.get("sport", "running")
        sport_config = get_sport_config(sport)

        log(f"Revisando: {name} / {date}")

        if scheduled_exists(client, name, date):
            log(f"Saltado: ya existe en calendario → {name}")
            continue

        log(f"Creando workout: {name} [{sport_config['sportTypeKey']}]")

        workout = build_workout(item)

        upload_method = getattr(client, sport_config["upload_method"])
        created = upload_method(workout)

        workout_id = created["workoutId"]

        log(f"Agendando para {date}")
        scheduled = client.schedule_workout(workout_id, date)

        log(f"OK workoutId: {workout_id}")
        log(f"OK scheduleId: {scheduled['workoutScheduleId']}")


init_state()


st.markdown('<p class="main-title">Garmin Training Sync</p>', unsafe_allow_html=True)
st.markdown(
    '<p class="subtitle">Convierte sesiones en lenguaje natural y sincronízalas con Garmin Connect.</p>',
    unsafe_allow_html=True,
)


left, right = st.columns([0.34, 0.66], gap="large")


with left:
    st.subheader("Autenticación Garmin")

    email = st.text_input("Email Garmin")
    password = st.text_input("Password Garmin", type="password")

    if st.button("Autenticar", use_container_width=True):
        try:
            with st.spinner("Autenticando con Garmin..."):
                authenticate(email, password)

            st.success("Autenticación correcta.")
            log("Autenticación correcta.")

        except Exception as e:
            st.error("No se pudo autenticar.")
            log(f"Error autenticando: {e}")

    if st.session_state.authenticated:
        st.markdown('<p class="status-ok">● Conectado</p>', unsafe_allow_html=True)
    else:
        st.markdown('<p class="status-error">● No autenticado</p>', unsafe_allow_html=True)

    st.divider()

    st.subheader("Acciones")

    generate_clicked = st.button("Generar Preview", use_container_width=True)
    sync_clicked = st.button("Sincronizar", use_container_width=True, type="primary")


with right:
    st.subheader("Sesiones de entrenamiento")

    default_text = """Fecha: 2026-07-01
Nombre: Mié01-Jul - Umbral

Sesión:
15 min calentamiento Z1
4 x 1 km @4:10-4:25 rec 2 min
10 min enfriamiento Z1"""

    session_text = st.text_area(
        "Pegá aquí el bloque compatible",
        value=default_text,
        height=320,
        label_visibility="collapsed",
    )

    if generate_clicked:
        try:
            plan = parse_input(session_text)
            st.session_state.plan = plan
            st.success(f"Preview generado. Workouts: {len(plan['workouts'])}")
            log(f"Preview generado. Workouts: {len(plan['workouts'])}")

        except Exception as e:
            st.error("No se pudo generar el preview.")
            log(f"Error generando preview: {e}")

    if st.session_state.plan:
        st.subheader("Preview")
        render_preview(st.session_state.plan)

        json_data = json.dumps(
            st.session_state.plan,
            indent=2,
            ensure_ascii=False,
        )

        st.download_button(
            "Descargar plan_semana.json",
            data=json_data,
            file_name="plan_semana.json",
            mime="application/json",
            use_container_width=True,
        )

    if sync_clicked:
        try:
            if not st.session_state.plan:
                st.session_state.plan = parse_input(session_text)

            with st.spinner("Sincronizando con Garmin Connect..."):
                sync_plan(st.session_state.plan)

            st.success("Sincronización finalizada.")

        except Exception as e:
            st.error("No se pudo sincronizar.")
            log(f"Error sincronizando: {e}")


st.divider()

st.subheader("Logs")

st.text_area(
    "Resultados",
    value="\n".join(st.session_state.logs),
    height=220,
    label_visibility="collapsed",
)