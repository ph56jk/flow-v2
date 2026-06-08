@echo off
cd /d "C:\Users\HAVI GROUP\Downloads\flowautomation"
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\HAVI GROUP\Downloads\flowautomation\scripts\start_flow_web_background.ps1" -AppHost "127.0.0.1" -Port "8000" -StartupDelaySeconds "15"
