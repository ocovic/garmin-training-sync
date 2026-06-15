# list_workouts.py

import os
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

client = Garmin(
    os.getenv("GARMIN_EMAIL"),
    os.getenv("GARMIN_PASSWORD")
)

client.login()

workouts = client.get_workouts()

for workout in workouts:
    print(
        f"{workout['workoutId']} | "
        f"{workout['workoutName']}"
    )