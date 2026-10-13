@echo off
REM Padel Hunter - dvoklik za pokretanje
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Prva instalacija...
  python -m venv .venv || goto :err
  .venv\Scripts\python -m pip install -q -r requirements.txt || goto :err
)
start "" http://127.0.0.1:8777
.venv\Scripts\python app.py
goto :eof
:err
echo Instalacija nije uspjela - je li instaliran Python 3.11+?
pause
