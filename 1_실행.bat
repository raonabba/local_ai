@echo off
rem 공문서 작성 보조 AI 실행 (파이썬만 있으면 됩니다. 인터넷 불필요)
cd /d "%~dp0"
set PY=
set PYW=
where py >nul 2>nul && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY (where python >nul 2>nul && (set "PY=python" & set "PYW=pythonw"))
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>nul
if errorlevel 1 goto oldpython
set "PYTHONPATH=%~dp0src"
start "" %PYW% -m gongmun_ai.gui
exit /b 0

:nopython
echo 파이썬이 설치되어 있지 않습니다.
echo python.org 에서 Python 3.12를 설치한 뒤 다시 실행하세요.
echo 설치 첫 화면에서 "Add python.exe to PATH"를 꼭 체크하세요.
start "" https://www.python.org/downloads/windows/
pause
exit /b 1

:oldpython
echo 파이썬 3.11 이상이 필요합니다. python.org 에서 Python 3.12를 설치하세요.
pause
exit /b 1
