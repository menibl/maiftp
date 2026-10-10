$env:MAIFOCUS_WEBHOOK_HOME = Join-Path $PSScriptRoot "data"
python -m uvicorn server:app --host 0.0.0.0 --port 8088 --reload
