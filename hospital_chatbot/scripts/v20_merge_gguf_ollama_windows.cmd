@echo off
setlocal
if "%~4"=="" (
  echo Usage: v20_merge_gguf_ollama_windows.cmd BASE_MODEL ADAPTER_DIR MERGED_OUT LLAMA_CPP_DIR
  exit /b 1
)
set BASE_MODEL=%~1
set ADAPTER_DIR=%~2
set MERGED_OUT=%~3
set LLAMA_CPP_DIR=%~4
set GGUF_OUT=%MERGED_OUT%_gguf
set MODELS_NAME=UPH_ChatBot
cd /d %~dp0\..
call .venv-train\Scripts\activate.bat
python training\merge_lora_qwen25_3b.py --base-model %BASE_MODEL% --adapter-dir %ADAPTER_DIR% --output-dir %MERGED_OUT%
if not exist %GGUF_OUT% mkdir %GGUF_OUT%
python "%LLAMA_CPP_DIR%\convert_hf_to_gguf.py" "%MERGED_OUT%" --outfile "%GGUF_OUT%\uph_chatbot_3b_f16.gguf"
"%LLAMA_CPP_DIR%\llama-quantize.exe" "%GGUF_OUT%\uph_chatbot_3b_f16.gguf" "%GGUF_OUT%\uph_chatbot_3b_q4_k_m.gguf" q4_k_m
copy /Y deployment\ollama\Modelfile.UPH_ChatBot.gguf "%GGUF_OUT%\Modelfile"
cd /d "%GGUF_OUT%"
ollama create UPH_ChatBot -f Modelfile
ollama run UPH_ChatBot
