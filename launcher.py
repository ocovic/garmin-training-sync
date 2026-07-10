import os
import shutil
import subprocess
import sys


def find_base_python():
    return shutil.which("python") or shutil.which("python3")


def ensure_venv(base_dir):
    venv_dir = os.path.join(base_dir, ".venv")
    venv_python = os.path.join(venv_dir, "Scripts", "python.exe")

    if os.path.exists(venv_python):
        return venv_python

    base_python = find_base_python()
    if not base_python:
        input(
            "No se encontro una instalacion de Python en el sistema. "
            "Instala Python (python.org) y volve a intentar. "
            "Presiona Enter para salir."
        )
        sys.exit(1)

    print("Primera vez: creando entorno virtual (.venv)...")
    subprocess.run([base_python, "-m", "venv", venv_dir], check=True)
    return venv_python


def dependencies_installed(python_exe):
    result = subprocess.run(
        [python_exe, "-c", "import streamlit"],
        capture_output=True,
    )
    return result.returncode == 0


def install_dependencies(python_exe, base_dir):
    print("Instalando dependencias (puede tardar unos minutos la primera vez)...")
    print()
    requirements_path = os.path.join(base_dir, "requirements.txt")
    subprocess.run(
        [python_exe, "-m", "pip", "install", "-r", requirements_path], check=True
    )


def main():
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    os.chdir(base_dir)

    print("==========================================")
    print("Garmin Training Sync")
    print("==========================================")
    print()

    try:
        python_exe = ensure_venv(base_dir)

        if not dependencies_installed(python_exe):
            install_dependencies(python_exe, base_dir)
    except subprocess.CalledProcessError as e:
        input(f"No se pudo preparar el entorno ({e}). Presiona Enter para salir.")
        sys.exit(1)

    print()
    print("Iniciando aplicacion...")
    print()

    result = subprocess.run([python_exe, "-m", "streamlit", "run", "app.py"])

    if result.returncode != 0:
        input("La aplicacion se cerro con un error. Presiona Enter para salir.")


if __name__ == "__main__":
    main()
