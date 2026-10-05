@echo off
setlocal
set PYTHONPATH=%~dp0
echo ===================================================
echo   OmniVault: Tri-Tier Archival & Instant Retrieval
echo   Opening dashboard at http://127.0.0.1:7890
echo ===================================================
start http://127.0.0.1:7890
python -m omnivault serve --port 7890
endlocal
