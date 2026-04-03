@echo off
color 0A
setlocal enabledelayedexpansion

set "DP=%~dp0"

if "%~1"=="" (
    echo.
    echo  No file detected.
    echo  Drop one or more TXT files onto this script.
    echo.
    pause
    exit /b
)

:: Collect all dropped TXT files
set "file_count=0"
:COLLECT
set /a file_count+=1
set "file[!file_count!]=%~1"
shift
if not "%~1"=="" goto COLLECT

:: ============================================================
::  Ask for translation direction
:: ============================================================
echo.
echo  -------------------------------------------------------
echo   Translation direction:
echo  -------------------------------------------------------
echo.
echo   [1]  English  --^>  German
echo   [2]  German   --^>  English
echo.
choice /c 12E /n /m "  Select [1-2, E = Abort]: "
if errorlevel 3 goto TTXT_END
if errorlevel 2 (set "DIR=de2en" & set "SRC_EXT=DE" & set "TGT_EXT=EN" & goto DIR_DONE)
if errorlevel 1 (set "DIR=en2de" & set "SRC_EXT=EN" & set "TGT_EXT=DE" & goto DIR_DONE)
:DIR_DONE

set "CTX=5"

:: ============================================================
::  Ollama prerequisites
:: ============================================================
echo.
echo  Checking Ollama ...
echo.

where ollama >nul 2>nul
if errorlevel 1 (
    echo  Ollama not found. Downloading installer ...
    curl -L https://ollama.com/download/OllamaSetup.exe -o "%temp%\OllamaSetup.exe"
    echo  Installing Ollama ...
    start /wait "" "%temp%\OllamaSetup.exe" /silent
    set "PATH=%PATH%;%LocalAppData%\Programs\Ollama"
    timeout /t 3 >nul
)

set "OLLAMA_HOST=127.0.0.1"
set "OLLAMA_FLASH_ATTENTION=1"
set "OLLAMA_KV_CACHE_TYPE=q4_0"
set "OLLAMA_GPU_OVERHEAD=0"
set "OLLAMA_NUM_PARALLEL=1"
set "OLLAMA_LOG_LEVEL=error"
set "OLLAMA_NUM_THREADS=8"

python -c "import requests" >nul 2>nul
if errorlevel 1 pip install requests

:: ============================================================
::  Translate loop
:: ============================================================
call :TXT_PROCESS
goto TTXT_END

:TXT_PROCESS
set "i=0"
:TXT_INNER
set /a i+=1
if !i! gtr !file_count! exit /b

set "src=!file[%i%]!"
for %%F in ("!src!") do (
    set "txt_path=%%~dpF"
    set "txt_base=%%~nF"
)

:: Bidirectional output naming
set "out_base=!txt_base!"
if /i "!txt_base:~-3!"==".!SRC_EXT!" set "out_base=!txt_base:~0,-3!"
set "out_file=!txt_path!!out_base!.!TGT_EXT!.txt"

echo.
echo  Translating: !txt_base!.txt  --^>  !out_base!.!TGT_EXT!.txt
echo.

python "%DP%translate_txt.py" "!src!" "!out_file!" !CTX! !DIR!

if exist "!out_file!" echo  Translation created successfully.
if not exist "!out_file!" echo  [ERROR] Translation failed.

goto TXT_INNER

:TTXT_END
echo.
color 0A
pause
color
exit /b
