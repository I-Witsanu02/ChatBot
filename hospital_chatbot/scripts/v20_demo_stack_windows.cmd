@echo off
setlocal
cd /d %~dp0\..
if not exist .venv (
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
cd nextjs_frontend
npm install
cd ..
if not exist data\master_kb.xlsx (
  echo ERROR: data\master_kb.xlsx not found
  exit /b 1
)
set PYTHONPATH=%CD%
set EMBEDDING_PROVIDER=ollama
set OLLAMA_EMBED_MODEL=bge-m3:latest
set OLLAMA_BASE_URL=http://127.0.0.1:11434
set OLLAMA_MODEL=UPH_ChatBot
python scripts\build_kb.py --input data\master_kb.xlsx --jsonl-output data\knowledge.jsonl --csv-output data\knowledge.csv --report-output data\kb_validation_report.json --manifest-output data\kb_manifest.json
python scripts\reindex_kb.py --knowledge data\knowledge.jsonl --db-dir chroma_db --collection hospital_faq --reset
start "UPH Backend" cmd /k "call .venv\Scripts\activate.bat && set PYTHONPATH=%CD% && set EMBEDDING_PROVIDER=ollama && set OLLAMA_EMBED_MODEL=bge-m3:latest && set OLLAMA_BASE_URL=http://127.0.0.1:11434 && set OLLAMA_MODEL=UPH_ChatBot && python -m uvicorn backend.app:app --reload --port 8000"
start "UPH Frontend" cmd /k "cd /d %CD%\nextjs_frontend && npm run dev"
echo Demo stack started.
