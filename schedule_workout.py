import os
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

client = Garmin(
    os.getenv("GARMIN_EMAIL"),
    os.getenv("GARMIN_PASSWORD")
)

client.login()

workout_id = 1598395369
date = "2026-06-15"  # YYYY-MM-DD

result = client.schedule_workout(workout_id, date)

print("Workout agendado:")
print(result)