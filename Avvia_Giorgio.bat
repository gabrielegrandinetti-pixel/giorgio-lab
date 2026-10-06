@echo off
cd /d "%~dp0"
py -u codex_app.py
if errorlevel 1 (
 echo.
 echo Se mancano dipendenze, esegui Installa_Dipendenze.bat e riprova.
 pause
)
