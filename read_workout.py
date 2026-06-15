# read_workout.py

import os
import json
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

client = Garmin(
    os.getenv("GARMIN_EMAIL"),
    os.getenv("GARMIN_PASSWORD")
)

client.login()

# Cambiá este ID por un workout que ya tenga ritmo objetivo
workout_id = 1599351383

workout = client.get_workout_by_id(workout_id)

with open("workout_debug.json", "w", encoding="utf-8") as file:
    json.dump(workout, file, indent=2, ensure_ascii=False)

print("Workout guardado en workout_debug.json")