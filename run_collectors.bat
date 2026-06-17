@echo off
chcp 65001 >nul
set PYTHON=C:\Users\salut\AppData\Local\Programs\Python\Python312\python.exe
set PROJECT=C:\Users\salut\sakyowon-ai

echo [%date% %time%] RiverWatch 데이터 수집 시작 >> "%PROJECT%\collector.log"

"%PYTHON%" "%PROJECT%\river_monitor.py" >> "%PROJECT%\collector.log" 2>&1
"%PYTHON%" "%PROJECT%\collectors\species.py" >> "%PROJECT%\collector.log" 2>&1
"%PYTHON%" "%PROJECT%\collectors\ehi.py" >> "%PROJECT%\collector.log" 2>&1
"%PYTHON%" "%PROJECT%\collectors\invasive_alert.py" >> "%PROJECT%\collector.log" 2>&1
"%PYTHON%" "%PROJECT%\collectors\policy_report.py" >> "%PROJECT%\collector.log" 2>&1

echo [%date% %time%] 수집 완료 >> "%PROJECT%\collector.log"
echo. >> "%PROJECT%\collector.log"
