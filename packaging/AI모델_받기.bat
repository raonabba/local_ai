@echo off
rem 무료 AI 모델(Qwen3 4B, Apache 2.0, 약 2.5GB)을 models 폴더로 받습니다.
rem 인터넷이 되는 PC에서 실행한 뒤, 폴더 전체를 업무 PC로 옮겨도 됩니다.
cd /d "%~dp0"
if exist "models\*.gguf" (
  echo models 폴더에 이미 모델이 있습니다.
  pause
  exit /b 0
)
echo 무료 AI 모델 Qwen3 4B(약 2.5GB)를 내려받습니다. 10~30분 걸릴 수 있습니다.
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
echo.
echo 받기가 끝났습니다. '공문서AI.exe'를 다시 실행하세요.
pause
