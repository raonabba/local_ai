@echo off
rem AI 기능(톤 조정, 기안문 초안) 설치: AI 엔진과 무료 모델을 받습니다.
rem 인터넷이 되는 PC에서 실행한 뒤, 폴더 전체를 업무 PC로 옮겨도 됩니다.
cd /d "%~dp0"
set PY=
set PYW=
where py >nul 2>nul && (set "PY=py -3" & set "PYW=pyw -3")
if not defined PY (where python >nul 2>nul && (set "PY=python" & set "PYW=pythonw"))
if not defined PY goto nopython
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>nul
if errorlevel 1 goto oldpython

echo [1/2] AI 엔진(llama.cpp, 무료)을 설치합니다...
%PY% -m pip install --user --upgrade --only-binary=llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu llama-cpp-python
if errorlevel 1 (
  echo.
  echo AI 엔진 설치에 실패했습니다. 파이썬 3.12에서 가장 잘 설치됩니다.
  pause
  exit /b 1
)

echo.
if exist "models\*.gguf" (
  echo [2/2] models 폴더에 이미 모델이 있어 내려받기를 건너뜁니다.
  goto done
)
echo [2/2] 무료 AI 모델 Qwen3 4B(약 2.5GB, Apache 2.0)를 내려받습니다.
echo       메모리 8GB 이상 PC에 맞는 크기입니다. 10~30분 걸릴 수 있습니다.
curl -fL --retry 3 -o "models\Qwen3-4B-Q4_K_M.gguf.part" https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf
if errorlevel 1 (
  del "models\Qwen3-4B-Q4_K_M.gguf.part" 2>nul
  echo.
  echo 모델을 내려받지 못했습니다. 브라우저에서 아래 주소의 Q4_K_M .gguf 파일을 받아
  echo 이 프로그램의 models 폴더에 넣어 주세요.
  echo   https://huggingface.co/Qwen/Qwen3-4B-GGUF
  start "" https://huggingface.co/Qwen/Qwen3-4B-GGUF
  pause
  exit /b 1
)
move /y "models\Qwen3-4B-Q4_K_M.gguf.part" "models\Qwen3-4B-Q4_K_M.gguf" >nul

:done
echo.
echo 설치가 끝났습니다. '1_실행.bat'으로 프로그램을 여세요.
pause
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
