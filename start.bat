@echo off
call "%~dp0tools\windows\_entry.bat" start %*
exit /b %errorlevel%
