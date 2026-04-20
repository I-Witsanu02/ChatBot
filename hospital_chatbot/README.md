# Hospital Chatbot Production Package 

# hospital_chatbot_edit

แพ็กนี้เป็นชุดเกือบครบ production สำหรับ hospital chatbot ที่รวมทั้ง
- RAG pipeline
- admin workflow
- evaluation / test set
- one-click model deploy
- one-click runtime setup
- full platform deploy
- Docker / Docker Compose
- nginx reverse proxy + SSL template
- backup / restore
- role-based admin auth

## โครงสร้างสำคัญ
- `backend/` API หลัก, retrieval, rerank, prompts, policies, audit, versioning, auth, model lock
- `scripts/` build/reindex/evaluate/deploy/backup/restore/smoke test/verify helpers
- `nextjs_frontend/` หน้าเว็บหลักเดิมที่เชื่อม API ใหม่แล้ว
- `frontend/` static admin UI และ prototype frontend
- `dashboard/` evaluation dashboard
- `deployment/` templates สำหรับ ollama, docker, nginx, runtime env
- `data/` workbook, knowledge, manifest, test set, model lock

## ลำดับใช้งานแบบไม่ใช้ Docker
```bash
pip install -r requirements.txt

python scripts/build_kb.py --input data/master_kb.xlsx \
  --jsonl-output data/knowledge.jsonl \
  --csv-output data/knowledge.csv \
  --report-output data/kb_validation_report.json \
  --manifest-output data/kb_manifest.json

python scripts/reindex_kb.py --knowledge data/knowledge.jsonl --db-dir chroma_db --collection hospital_faq --reset
python scripts/generate_test_set.py --knowledge data/knowledge.jsonl --output data/regression_test_set_realistic.jsonl
python scripts/evaluate.py --test-set data/regression_test_set_realistic.jsonl --report-output data/evaluation_report.json --details-output data/evaluation_details.jsonl --manifest data/kb_manifest.json
uvicorn backend.app:app --reload --port 8000
```

## One-click deploy ฝั่งโมเดล
```bash
bash scripts/deploy_one_click.sh
```
คู่มือ: `docs/one_click_deploy_th.md`

## One-click runtime setup ฝั่งระบบ RAG
```bash
bash scripts/runtime_setup_one_click.sh
```
คู่มือ: `docs/one_click_runtime_setup_th.md`

## Full platform deploy
```bash
bash scripts/deploy_full_platform.sh
```
คู่มือ: `docs/full_platform_deploy_th.md`

## Backup / Restore
สร้าง backup
```bash
bash scripts/backup_platform.sh
```
restore backup
```bash
bash scripts/restore_platform_backup.sh --archive backups/your_backup.tar.gz
```
คู่มือ: `docs/backup_restore_th.md`

## Admin auth
รองรับ role:
- viewer
- editor
- admin

รองรับ auth ผ่าน:
- `X-Admin-Token`
- Basic Auth

คู่มือ: `docs/admin_auth_th.md`

## Docker / Docker Compose
```bash
cp deployment/docker/.env.example .env
bash scripts/create_nginx_htpasswd.sh deployment/nginx/.htpasswd admin change-me

docker compose up --build -d
```
ถ้าจะเปิด dashboard ด้วย
```bash
docker compose --profile dashboard up --build -d
```
คู่มือ: `docs/docker_nginx_deploy_th.md`

## SSL / Domain
- แก้ `YOUR_DOMAIN` ใน `deployment/nginx/conf.d/site-ssl.conf`
- วาง cert ที่ `deployment/nginx/certs/fullchain.pem` และ `deployment/nginx/certs/privkey.pem`
- รัน
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

## หน้าเว็บ
- Next.js frontend: `nextjs_frontend/`
- Static admin UI: `/admin-ui`
- API health: `/health`
- Guide: `/guide`

## หมายเหตุสำคัญ
- สำหรับ production จริง แนะนำใช้ nginx + Docker Compose + backup schedule
- admin UI ควรถูกป้องกันทั้งที่ nginx และ backend พร้อมกัน
- ก่อน deploy ใหญ่ทุกครั้ง ควรทำ backup ก่อน


## Handoff docs for hospital IT team

- docs/hospital_it_handoff_th.md
- docs/production_go_live_checklist_th.md
- docs/post_deploy_checklist_th.md
- docs/sop_kb_update_th.md
- docs/sop_rollback_th.md
- docs/admin_manual_th.md
- docs/ops_runbook_th.md
- docs/handoff_acceptance_form_th.md

