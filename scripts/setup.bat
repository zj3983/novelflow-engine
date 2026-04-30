@echo off
setlocal

uv sync --extra dev
if errorlevel 1 exit /b %errorlevel%

cd apps\web
npm ci
if errorlevel 1 exit /b %errorlevel%

echo Setup complete.
