@echo off
rem 무료 AI 모델을 models 폴더로 받습니다. (인터넷이 되는 PC에서 실행한 뒤 폴더째 옮겨도 됩니다)
cd /d "%~dp0"
echo.
echo  무료 AI 모델을 고르세요.
echo.
echo   1. 저사양용  Qwen3 1.7B  (약 1.1GB, 메모리 4GB 이상, 빠름)   - 공공기관 일반 PC 권장
echo   2. 표준      Qwen3 4B    (약 2.5GB, 메모리 8GB 이상, 문장이 더 좋음)
echo.
echo   둘 다 받아 두면 프로그램이 PC 메모리에 맞는 것을 골라 씁니다.
echo.
choice /c 12 /n /m "번호를 누르세요 (1 또는 2): "
if errorlevel 2 (
  set "NAME=Qwen3-4B-Q4_K_M.gguf"
  set "URL=https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf"
  set "PAGE=https://huggingface.co/Qwen/Qwen3-4B-GGUF"
) else (
  set "NAME=Qwen3-1.7B-Q4_K_M.gguf"
  set "URL=https://huggingface.co/unsloth/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q4_K_M.gguf"
  set "PAGE=https://huggingface.co/unsloth/Qwen3-1.7B-GGUF"
)
if exist "models\%NAME%" (
  echo models 폴더에 이미 %NAME% 이 있습니다.
  pause
  exit /b 0
)
echo.
echo %NAME% 를 내려받습니다. 몇 분에서 수십 분 걸릴 수 있습니다.
curl -fL --retry 3 -o "models\%NAME%.part" "%URL%"
if errorlevel 1 goto failed
move /y "models\%NAME%.part" "models\%NAME%" >nul
echo.
echo 받기가 끝났습니다. 공문서AI.exe를 실행하세요(이미 켜져 있으면 [초안 작성]을 누르면 바로 찾습니다).
pause
exit /b 0

:failed
del "models\%NAME%.part" 2>nul
echo.
echo 모델을 내려받지 못했습니다. 브라우저에서 아래 페이지의 Q4_K_M .gguf 파일을 받아
echo 이 프로그램의 models 폴더에 넣어 주세요.
echo   %PAGE%
start "" "%PAGE%"
pause
exit /b 1
