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

scheduled = client.get_scheduled_workouts(2026, 6)

print(type(scheduled))
print(json.dumps(scheduled, indent=2, ensure_ascii=False))