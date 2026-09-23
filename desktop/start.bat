@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
 where python >nul 2>nul
 if errorlevel 1 goto :no_python
 set "PY_CMD=python"
) else (
 set "PY_CMD=py -3"
)
if not exist .venv\Scripts\python.exe %PY_CMD% -m venv .venv
if not exist .venv\Scripts\python.exe goto :fail
.venv\Scripts\python.exe -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if errorlevel 1 goto :no_python
.venv\Scripts\python.exe -c "import fastapi,uvicorn,cv2,PIL,httpx,imageio_ffmpeg" >nul 2>nul
if errorlevel 1 (
 echo Installing pinned program dependencies. No AI models will be downloaded.
 .venv\Scripts\python.exe -m pip install -r requirements.txt
 if errorlevel 1 goto :fail
)
.venv\Scripts\python.exe launcher.py %*
if errorlevel 1 goto :fail
exit /b 0
:no_python
echo Python 3.11 or newer is required. Install it from python.org.
pause
exit /b 1
:fail
echo Startup failed. This is an isolated workbench; the original EvoVid was not changed.
pause
exit /b 1
