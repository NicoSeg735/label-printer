@echo off
cd /d "%~dp0"
start "Impresor de etiquetas" /b pythonw.exe "%~dp0web_app.py"
