@echo off
REM Build Margin Mate as a Windows .exe
REM Run from the project root: build_windows.bat

echo =^> Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo =^> Building app...
pyinstaller margin_mate.spec --clean

echo.
echo Done! Executable is at: dist\MarginMate.exe
pause
