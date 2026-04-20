@echo off
setlocal
cd /d %~dp0..
ollama create UPH_ChatBot -f deployment\ollama\Modelfile.UPH_ChatBot.typhoon
endlocal
