@echo off
setlocal
cd /d "%~dp0"
echo ================================================
echo CleanConnect - REAL ML setup
 echo ================================================
python -m pip install -r requirements.txt
if errorlevel 1 goto failed
python train_model.py
if errorlevel 1 goto failed
echo.
echo ML model is trained and ready.
echo Start the website with: python app.py
pause
exit /b 0
:failed
echo.
echo ML setup failed. Check the error above.
pause
exit /b 1
