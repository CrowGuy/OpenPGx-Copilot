# 本機資料庫（開發與測試）

伺服器的設定見 `docs/postgres-docker-playbook.md`。這個目錄放兩邊共用的東西：`meta` 的編號 migration（`migrations/`）與 Release schema 的 DDL（`release_schema.sql`），以及本機用的 Compose 設定。

## 啟動

```bash
docker compose -f db/compose.yaml up -d
docker compose -f db/compose.yaml logs migrate   # 最後一行應該是 dev database ready
```

- 在 `127.0.0.1:5432` 起 PostgreSQL 18，包含 `openpgx`（開發用）與 `openpgx_test`（測試用）兩個資料庫。
- `migrate` 服務會把 `migrations/` 裡的每個檔案套用到兩個資料庫，並設定開發用密碼：`etl_writer`／`etl_writer`、`analyst_ro`／`analyst_ro`。再執行一次同一個指令就會重新套用，所以每個 migration 都必須可以重複執行。
- 全部重來：`docker compose -f db/compose.yaml down -v`（會刪除 volume）。

## Load 與 Promote

```bash
pip install "psycopg[binary]"
export PGHOST=127.0.0.1 PGDATABASE=openpgx PGUSER=etl_writer PGPASSWORD=etl_writer   # 或使用 ~/.pgpass
python tools/gwas_release_loader.py load \
  --snapshot-dir raw/gwas_catalog/r2026-08-22 \
  --curation-contract raw/gwas_catalog/contracts/gwas_curation_contract.json \
  --dataset-contract raw/gwas_catalog/contracts/gwas_dataset_contract.json
python tools/gwas_release_loader.py promote --release r2026-08-22 --approved-by <你的名字>
```

同一個 Release 不能再 load 一次。Promote 只接受 `candidate`，並在同一個 transaction 內刪除最近 Promote 過的 3 個 Release（`active` 與 `retired`）以外的 `retired` schema；`candidate` 不佔名額也不會被刪；`meta.release` 的紀錄保留。

用團隊成員的身分查詢：

```bash
psql "host=127.0.0.1 dbname=openpgx user=analyst_ro password=analyst_ro" \
  -c "SELECT * FROM gwas.study WHERE study_accession = 'GCST006134'"
```

## 測試

```bash
python -m unittest discover -s tests
```

測試使用 `openpgx_test`；連不到資料庫或沒有安裝 `psycopg` 時會 skip。要改連其他資料庫，設定 `OPENPGX_TEST_DSN`（`etl_writer`）與 `OPENPGX_TEST_ANALYST_DSN`（`analyst_ro`）。測試會刪除該資料庫中所有 `gwas_r*` schema，並清空 `meta.release`。
