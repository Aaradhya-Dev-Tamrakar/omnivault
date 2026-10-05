@echo off
setlocal
set PYTHONPATH=%~dp0
python -m omnivault %*
endlocal
