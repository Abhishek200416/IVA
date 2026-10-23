@echo off
setlocal
set REPO_ROOT=%~dp0..\..
"%REPO_ROOT%\.venv\Scripts\python.exe" "%~dp0run_agi_17.py" %*
exit /b %ERRORLEVEL%
