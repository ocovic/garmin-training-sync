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

print(f"Workouts encontrados: {len(workouts)}")

for w in workouts[:5]:
    print("----------------")
    print(w)