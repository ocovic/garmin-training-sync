import os
from dotenv import load_dotenv
from garminconnect import Garmin
from garminconnect.workout import (
    RunningWorkout,
    WorkoutSegment,
    create_warmup_step,
    create_cooldown_step,
)

load_dotenv()

client = Garmin(
    os.getenv("GARMIN_EMAIL"),
    os.getenv("GARMIN_PASSWORD")
)

client.login()

workout = RunningWorkout(
    workoutName="Test - Rodaje Suave 30min",
    description="Entrenamiento creado desde Python",
    estimatedDurationInSecs=1800,
    workoutSegments=[
        WorkoutSegment(
            segmentOrder=1,
            sportType={
                "sportTypeId": 1,
                "sportTypeKey": "running"
            },
            workoutSteps=[
                create_warmup_step(300.0, step_order=1),
                create_cooldown_step(1500.0, step_order=2)
            ]
        )
    ]
)

result = client.upload_running_workout(workout)

print("Workout creado:")
print(result)