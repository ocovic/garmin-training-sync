import argparse
import json
import os
from dotenv import load_dotenv
from garminconnect import Garmin
from garminconnect.workout import (
    RunningWorkout,
    CyclingWorkout,
    WorkoutSegment,
    create_warmup_step,
    create_interval_step,
    create_recovery_step,
    create_cooldown_step,
    create_repeat_group,
)

load_dotenv()


PACE_TARGET_TYPE = {
    "workoutTargetTypeId": 6,
    "workoutTargetTypeKey": "pace.zone",
    "displayOrder": 6,
}

HEART_RATE_TARGET_TYPE = {
    "workoutTargetTypeId": 4,
    "workoutTargetTypeKey": "heart.rate.zone",
    "displayOrder": 4,
}

TIME_END_CONDITION = {
    "conditionTypeId": 2,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}

DISTANCE_END_CONDITION = {
    "conditionTypeId": 3,
    "conditionTypeKey": "distance",
    "displayOrder": 3,
    "displayable": True,
}

LAP_BUTTON_END_CONDITION = {
    "conditionTypeId": 1,
    "conditionTypeKey": "lap.button",
    "displayOrder": 1,
    "displayable": True,
}

KILOMETER_UNIT = {
    "unitId": 2,
    "unitKey": "kilometer",
    "factor": 100000.0,
}

def get_sport_config(sport: str) -> dict:
    sport = (sport or "running").lower()

    if sport == "running":
        return {
            "sportTypeId": 1,
            "sportTypeKey": "running",
            "workout_class": RunningWorkout,
            "upload_method": "upload_running_workout",
        }

    if sport in ["cycling", "mtb", "bike", "biking"]:
        return {
            "sportTypeId": 2,
            "sportTypeKey": "cycling",
            "workout_class": CyclingWorkout,
            "upload_method": "upload_cycling_workout",
        }

    raise ValueError(f"Deporte no soportado: {sport}")


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Muestra lo que haría sin crear ni agendar workouts",
    )
    return parser.parse_args()


def get_client() -> Garmin:
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if not email or not password:
        raise ValueError("Faltan GARMIN_EMAIL o GARMIN_PASSWORD en .env")

    client = Garmin(email, password)
    client.login()
    return client


def pace_to_mps(pace: str) -> float:
    minutes, seconds = map(int, pace.split(":"))
    total_seconds = minutes * 60 + seconds
    return 1000 / total_seconds


def build_target(step: dict):
    target = step.get("target")

    if not target:
        return None

    if target["type"] == "pace":
        fast = pace_to_mps(target["min"])
        slow = pace_to_mps(target["max"])

        return {
            "target_type": PACE_TARGET_TYPE,
            "targetValueOne": fast,
            "targetValueTwo": slow,
        }

    if target["type"] == "heart_rate":
        return {
            "target_type": HEART_RATE_TARGET_TYPE,
            "targetValueOne": float(target["min"]),
            "targetValueTwo": float(target["max"]),
        }
    
    if target["type"] == "hr_zone":
        return {
            "target_type": HEART_RATE_TARGET_TYPE,
            "targetValueOne": None,
            "targetValueTwo": None,
            "zoneNumber": int(target["zone"]),
        }

    raise ValueError(f"Target no soportado: {target['type']}")


def apply_target(step_obj, step: dict):
    target = build_target(step)

    if not target:
        return step_obj

    step_obj.targetType = target["target_type"]
    step_obj.targetValueOne = target.get("targetValueOne")
    step_obj.targetValueTwo = target.get("targetValueTwo")

    if "zoneNumber" in target:
        step_obj.zoneNumber = target["zoneNumber"]

    return step_obj


def apply_end_condition(step_obj, step: dict):
    has_duration = "duration_seconds" in step
    has_distance = "distance_meters" in step
    has_lap = step.get("until_lap") is True

    condition_count = sum([has_duration, has_distance, has_lap])

    if condition_count > 1:
        raise ValueError(
            "Un paso solo puede tener una condición: duration_seconds, distance_meters o until_lap"
        )

    if condition_count == 0:
        raise ValueError(
            "Cada paso debe tener duration_seconds, distance_meters o until_lap"
        )

    if has_duration:
        step_obj.endCondition = TIME_END_CONDITION
        step_obj.endConditionValue = float(step["duration_seconds"])
        step_obj.preferredEndConditionUnit = None

    if has_distance:
        step_obj.endCondition = DISTANCE_END_CONDITION
        step_obj.endConditionValue = float(step["distance_meters"])
        step_obj.preferredEndConditionUnit = KILOMETER_UNIT

    if has_lap:
        step_obj.endCondition = LAP_BUTTON_END_CONDITION
        step_obj.endConditionValue = float(step.get("estimated_duration_seconds", 0))
        step_obj.preferredEndConditionUnit = None

    return step_obj


def estimate_step_duration(step: dict) -> int:
    if "duration_seconds" in step:
        return int(step["duration_seconds"])

    if "estimated_duration_seconds" in step:
        return int(step["estimated_duration_seconds"])

    return 0


def calculate_duration(raw_steps: list[dict]) -> int:
    total = 0

    for step in raw_steps:
        if step["type"] == "repeat":
            total += int(step["count"]) * calculate_duration(step["steps"])
        else:
            total += estimate_step_duration(step)

    return total


def _pace_str_to_min(pace: str) -> float:
    """Convert 'M:SS' pace string to decimal minutes per km."""
    parts = pace.split(":")
    return int(parts[0]) + int(parts[1]) / 60 if len(parts) == 2 else float(parts[0])


def calculate_distance(raw_steps: list[dict]) -> float:
    total = 0.0

    for step in raw_steps:
        if step["type"] == "repeat":
            total += int(step["count"]) * calculate_distance(step["steps"])
        elif step.get("distance_meters", 0):
            total += float(step["distance_meters"])
        else:
            # Estimate distance from duration + pace target when no explicit distance
            duration_s = float(step.get("duration_seconds") or step.get("estimated_duration_seconds") or 0)
            target = step.get("target") or {}
            if duration_s > 0 and target.get("type") == "pace":
                pace_min = target.get("min") or target.get("max")
                if pace_min:
                    avg_pace = (
                        (_pace_str_to_min(target["min"]) + _pace_str_to_min(target["max"])) / 2
                        if target.get("max")
                        else _pace_str_to_min(pace_min)
                    )
                    total += (duration_s / 60) / avg_pace * 1000

    return total


def build_step(step: dict, order: int):
    step_type = step["type"]

    if step_type == "repeat":
        repeat_steps = [
            build_step(child_step, child_index + 1)
            for child_index, child_step in enumerate(step["steps"])
        ]

        return create_repeat_group(
            iterations=int(step["count"]),
            workout_steps=repeat_steps,
            step_order=order,
        )

    dummy_duration = float(step.get("duration_seconds", 1))

    if step_type == "warmup":
        step_obj = create_warmup_step(dummy_duration, step_order=order)
    elif step_type == "run":
        step_obj = create_interval_step(dummy_duration, step_order=order)
    elif step_type == "recovery":
        step_obj = create_recovery_step(dummy_duration, step_order=order)
    elif step_type == "cooldown":
        step_obj = create_cooldown_step(dummy_duration, step_order=order)
    else:
        raise ValueError(f"Tipo de paso no soportado: {step_type}")

    step_obj = apply_end_condition(step_obj, step)
    step_obj = apply_target(step_obj, step)

    return step_obj


def build_workout(item: dict):
    sport = item.get("sport", "running")
    sport_config = get_sport_config(sport)

    steps = [
        build_step(step, index + 1)
        for index, step in enumerate(item["steps"])
    ]

    total_duration = item.get("estimated_duration_seconds")
    if total_duration is None:
        total_duration = calculate_duration(item["steps"])

    total_distance = item.get("estimated_distance_meters")
    if total_distance is None:
        total_distance = calculate_distance(item["steps"]) or None

    workout_class = sport_config["workout_class"]

    return workout_class(
        workoutName=item["name"],
        description=item.get("description"),
        estimatedDurationInSecs=total_duration,
        estimatedDistanceInMeters=total_distance,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType={
                    "sportTypeId": sport_config["sportTypeId"],
                    "sportTypeKey": sport_config["sportTypeKey"],
                },
                workoutSteps=steps,
            )
        ],
    )


def scheduled_exists(client: Garmin, workout_name: str, date: str) -> bool:
    year, month, _ = map(int, date.split("-"))

    response = client.get_scheduled_workouts(year, month)
    calendar_items = response.get("calendarItems", [])

    for item in calendar_items:
        if item.get("itemType") != "workout":
            continue

        if item.get("date") == date and item.get("title") == workout_name:
            return True

    return False


def format_target(step: dict) -> str:
    target = step.get("target")

    if not target:
        return ""

    if target["type"] == "pace":
        return f" | pace {target['min']}-{target['max']}/km"

    if target["type"] == "heart_rate":
        return f" | FC {target['min']}-{target['max']} ppm"

    if target["type"] == "hr_zone":
        return f" | FC Zona {target['zone']}"

    return f" | target {target['type']}"


def format_end_condition(step: dict) -> str:
    if step.get("until_lap") is True:
        estimate = step.get("estimated_duration_seconds")

        if estimate:
            return f"hasta pulsar Lap ~ {estimate} segundos"

        return "hasta pulsar Lap"

    if "duration_seconds" in step:
        return f"{step['duration_seconds']} segundos"

    if "distance_meters" in step:
        return f"{step['distance_meters']} metros"

    return "sin condición"


def preview_steps(raw_steps: list[dict], indent: int = 0):
    prefix = " " * indent

    for step in raw_steps:
        step_type = step["type"]

        if step_type == "repeat":
            print(f"{prefix}- repeat x{step['count']}")
            preview_steps(step["steps"], indent + 4)
        else:
            print(
                f"{prefix}- {step_type}: "
                f"{format_end_condition(step)}"
                f"{format_target(step)}"
            )


def preview_workout(item: dict):
    total_duration = item.get("estimated_duration_seconds")
    if total_duration is None:
        total_duration = calculate_duration(item["steps"])

    total_distance = item.get("estimated_distance_meters")
    if total_distance is None:
        total_distance = calculate_distance(item["steps"])

    print("PREVIEW: se crearía y agendaría este workout")
    print(f"Nombre: {item['name']}")
    print(f"Fecha: {item['date']}")
    print(f"Deporte: {item.get('sport', 'running')}")
    print(f"Descripción: {item.get('description', '')}")
    print(f"Duración estimada: {total_duration} segundos")
    print(f"Distancia estimada: {total_distance} metros")
    print("Pasos:")
    preview_steps(item["steps"])


def main():
    args = get_args()
    preview = args.preview

    client = get_client()

    with open("plan_semana.json", "r", encoding="utf-8") as file:
        plan = json.load(file)

    for item in plan["workouts"]:
        name = item["name"]
        date = item["date"]

        print(f"Revisando: {name} / {date}")

        if scheduled_exists(client, name, date):
            print("Saltado: ya existe en calendario")
            print("-" * 40)
            continue

        if preview:
            preview_workout(item)
            print("-" * 40)
            continue

        sport = item.get("sport", "running")
        sport_config = get_sport_config(sport)

        print(f"Creando workout: {name} [{sport_config['sportTypeKey']}]")

        workout = build_workout(item)

        upload_method = getattr(client, sport_config["upload_method"])
        created = upload_method(workout)
        workout_id = created["workoutId"]

        print(f"Agendando {name} para {date}")
        scheduled = client.schedule_workout(workout_id, date)

        print(f"OK - workoutId: {workout_id}")
        print(f"OK - scheduleId: {scheduled['workoutScheduleId']}")
        print("-" * 40)


if __name__ == "__main__":
    main()