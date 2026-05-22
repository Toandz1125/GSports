# GSports setup (Windows, PowerShell)

This guide gets a fresh clone running locally on Windows.

## Prerequisites

- Python 3.12 (recommended). Pillow 10.3.0 has a prebuilt wheel for 3.12 on Windows.
- Git (to clone the repo).

## Quick start

1) Clone and enter the project folder:

```powershell
git clone <your-repo-url>
cd GSports
```
If project haven't folder media, static or template. You can create it using:
```powershell
mkdir static 
mkdir static\css
mkdir static\js
mkdir static\img 

mkdir -p media

mkdir -p templates/tasks/components
```powershell

2) Create and activate the virtual environment:

```powershell
py -3.12 -m venv gsports_env
.\gsports_env\Scripts\Activate
```

If activation is blocked, run this once and try again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

3) Install dependencies:

```powershell
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

4) Apply migrations and create an admin user:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

5) Run the development server:

```powershell
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

## Notes

- If `py -3.12` is not found, run `py -0` to list installed versions and install Python 3.12 from python.org.
- Using Python 3.14 can cause Pillow to build from source on Windows, which may fail. Use 3.12 to avoid that.

## Common commands

```powershell
# Leave the virtual environment
Deactivate

# Run tests (when available)
python manage.py test
```
