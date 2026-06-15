import os
from dotenv import load_dotenv
from garminconnect import Garmin

load_dotenv()

email = os.getenv("GARMIN_EMAIL")
password = os.getenv("GARMIN_PASSWORD")

client = Garmin(email, password)
client.login()

print("Login correcto")

profile = client.get_user_profile()
print("Perfil:")
print(profile)

methods = [m for m in dir(client) if "workout" in m.lower()]
print("Métodos workout:")
print(methods)