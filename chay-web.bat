@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Chua co moi truong ao. Dang tao .venv va cai thu vien...
  python -m venv .venv
  if errorlevel 1 (
    echo Khong tao duoc .venv. Hay cai Python 3.12 va chon Add python.exe to PATH.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Cai thu vien that bai.
    pause
    exit /b 1
  )
)

echo Mo http://127.0.0.1:8765
start "" http://127.0.0.1:8765
".venv\Scripts\python.exe" main.py
pause
