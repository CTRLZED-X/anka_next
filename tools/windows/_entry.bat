@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0..\.."
rem Stage 0 runs in cmd.exe; it does not require Python or installed packages.
set "ANKA_BOOTDIR=%CD%\runtime\bootstrap"
if not exist "%ANKA_BOOTDIR%" mkdir "%ANKA_BOOTDIR%" 2>nul
if not exist "%ANKA_BOOTDIR%" set "ANKA_BOOTDIR=%TEMP%\ANKA_NEXT\bootstrap"
if not exist "%ANKA_BOOTDIR%" mkdir "%ANKA_BOOTDIR%" 2>nul
set "ANKA_BOOTLOG=%ANKA_BOOTDIR%\inv_%RANDOM%_%RANDOM%.log"
>"%ANKA_BOOTLOG%" echo STAGE=BAT_ENTERED
>>"%ANKA_BOOTLOG%" echo LOCAL_START=%DATE% %TIME%
>>"%ANKA_BOOTLOG%" echo OPERATION=%~1
set "PYTHONPATH=%CD%\src"
set "ANKA_PYTHON="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.13 -V >nul 2>nul
    if not errorlevel 1 set "ANKA_PYTHON=py -3.13"
)
if not defined ANKA_PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "ANKA_PYTHON=python"
)
if not defined ANKA_PYTHON (
    >>"%ANKA_BOOTLOG%" echo STAGE=PYTHON_NOT_FOUND
    echo ANKA_STATUS=BLOCKED
    echo ANKA_FAILURE=PYTHON_NOT_FOUND
    echo ANKA_BOOTLOG=%ANKA_BOOTLOG%
    exit /b 40
)
>>"%ANKA_BOOTLOG%" echo STAGE=PYTHON_FOUND
if /I "%~1"=="setup" (
    %ANKA_PYTHON% -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,13) else 1)" >nul 2>nul
    if errorlevel 1 (
        >>"%ANKA_BOOTLOG%" echo STAGE=PYTHON_VERSION_UNSUPPORTED
        echo ANKA_STATUS=BLOCKED
        echo ANKA_FAILURE=PYTHON_VERSION_UNSUPPORTED
        echo ANKA_BOOTLOG=%ANKA_BOOTLOG%
        exit /b 40
    )
    >>"%ANKA_BOOTLOG%" echo STAGE=VERIFY_RELEASE_INTEGRITY
    %ANKA_PYTHON% "tools\bootstrap_release_integrity.py" >>"%ANKA_BOOTLOG%" 2>&1
    if errorlevel 1 goto SETUP_RELEASE_INTEGRITY_FAILED
    if not exist ".venv\Scripts\python.exe" (
        >>"%ANKA_BOOTLOG%" echo STAGE=CREATE_VENV
        %ANKA_PYTHON% -m venv ".venv" >>"%ANKA_BOOTLOG%" 2>&1
        if errorlevel 1 goto SETUP_DEPENDENCY_FAILED
    )
    >>"%ANKA_BOOTLOG%" echo STAGE=INSTALL_DEPENDENCIES
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "requirements-p1.txt" >>"%ANKA_BOOTLOG%" 2>&1
    if errorlevel 1 goto SETUP_DEPENDENCY_FAILED
    rem Observe-only Windows capture is part of the normal prepared runtime.
    rem Technical ports/interfaces are discovered internally at start; the
    rem operator never has to configure them to obtain the dependency.
    >>"%ANKA_BOOTLOG%" echo STAGE=INSTALL_CAPTURE_DEPENDENCIES
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r "requirements-windows-capture.txt" >>"%ANKA_BOOTLOG%" 2>&1
    if errorlevel 1 goto SETUP_DEPENDENCY_FAILED
    >>"%ANKA_BOOTLOG%" echo STAGE=PROBE_CAPTURE_PREREQUISITES
    ".venv\Scripts\python.exe" "tools\windows_capture_prereq.py" >>"%ANKA_BOOTLOG%" 2>&1
    if errorlevel 1 >>"%ANKA_BOOTLOG%" echo STAGE=CAPTURE_PREREQUISITE_PROBE_FAILED
    >>"%ANKA_BOOTLOG%" echo STAGE=PREPARE_OPTIONAL_UNITY_BRIDGE
    ".venv\Scripts\python.exe" "tools\windows_bridge_setup.py" >>"%ANKA_BOOTLOG%" 2>&1
    if errorlevel 1 >>"%ANKA_BOOTLOG%" echo STAGE=BRIDGE_PREPARATION_HELPER_FAILED
)
if exist ".venv\Scripts\python.exe" set "ANKA_PYTHON=.venv\Scripts\python.exe"
if /I "%~1"=="start" (
    echo ANKA read-only live acceptance check starting.
    echo Physical input is disabled; keep the intended Dofus clients open.
)
%ANKA_PYTHON% -m anka_app.cli %* >>"%ANKA_BOOTLOG%" 2>&1
set "ANKA_EXIT=%errorlevel%"
>>"%ANKA_BOOTLOG%" echo EXIT_CODE=%ANKA_EXIT%
if "%ANKA_EXIT%"=="0" (
    if /I "%~1"=="setup" (
        echo.
        echo ============================================================
        echo ANKA SETUP COMPLETED SUCCESSFULLY
        echo The installation and offline verification passed.
        echo Live prerequisite status is shown below; PENDING means start will explain what is missing.
        echo Next: open Dofus, then run start.bat for read-only live checks.
        echo ============================================================
    )
    findstr /B /C:"CAPTURE_PREREQ=" /C:"BRIDGE_SETUP=" /C:"ANKA_STATUS=" /C:"ANKA_EVIDENCE=" "%ANKA_BOOTLOG%" 2>nul
) else if "%ANKA_EXIT%"=="130" (
    echo.
    echo ANKA operation was interrupted safely by the operator.
    findstr /B /C:"ANKA_STATUS=" /C:"ANKA_FAILURE=" /C:"ANKA_BUNDLE=" /C:"ANKA_EVIDENCE=" "%ANKA_BOOTLOG%" 2>nul
) else (
    echo.
    echo ANKA operation was blocked. Key diagnostics:
    findstr /B /C:"ANKA_STATUS=" /C:"ANKA_FAILURE=" /C:"ANKA_BUNDLE=" /C:"ANKA_EVIDENCE=" "%ANKA_BOOTLOG%" 2>nul
)
echo ANKA_BOOTLOG=%ANKA_BOOTLOG%
exit /b %ANKA_EXIT%

:SETUP_RELEASE_INTEGRITY_FAILED
>>"%ANKA_BOOTLOG%" echo STAGE=RELEASE_INTEGRITY_FAILED
%ANKA_PYTHON% "tools\bootstrap_failure.py" RELEASE_INTEGRITY_FAILED >>"%ANKA_BOOTLOG%" 2>&1
>>"%ANKA_BOOTLOG%" echo EXIT_CODE=40
set "ANKA_FAILURE=RELEASE_INTEGRITY_FAILED"
echo ANKA_STATUS=BLOCKED
echo ANKA_FAILURE=%ANKA_FAILURE%
echo Setup stopped because the extracted release does not match its manifest.
echo Re-extract a clean ANKA_NEXT ZIP before trying setup again.
echo ANKA_BOOTLOG=%ANKA_BOOTLOG%
exit /b 40

:SETUP_DEPENDENCY_FAILED
>>"%ANKA_BOOTLOG%" echo STAGE=DEPENDENCY_INSTALL_FAILED
%ANKA_PYTHON% "tools\bootstrap_failure.py" DEPENDENCY_INSTALL_FAILED >>"%ANKA_BOOTLOG%" 2>&1
>>"%ANKA_BOOTLOG%" echo EXIT_CODE=40
set "ANKA_FAILURE=DEPENDENCY_INSTALL_FAILED"
echo ANKA_STATUS=BLOCKED
echo ANKA_FAILURE=%ANKA_FAILURE%
echo Setup could not install a required dependency. See the bootstrap log below.
echo ANKA_BOOTLOG=%ANKA_BOOTLOG%
exit /b 40
