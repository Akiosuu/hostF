@echo off
echo Starting debug script...
echo Argument 1: "%~1"
echo Argument 2: "%~2"
echo.

if "%~1"=="" (
    echo ERROR: No first argument provided
    echo Usage: debug.bat "source_folder" "output_folder"
    pause
    exit /b 1
)

echo First argument exists: %~1
echo Testing if directory exists...

if not exist "%~1" (
    echo ERROR: Directory does not exist: %~1
    pause
    exit /b 1
)

echo Directory exists!
echo Testing ffmpeg...

ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo ERROR: ffmpeg not found
    pause
    exit /b 1
)

echo ffmpeg is working!
echo Script completed successfully
pause
