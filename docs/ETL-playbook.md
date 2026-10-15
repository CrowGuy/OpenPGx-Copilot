# ETL Playbook：換版

適用對象：在團隊伺服器上執行換版的團隊成員。
適用範圍：把一個 RawSnapshot 載入成 Candidate、審查、Promote 成 Active Release，以及失敗時的復原、`meta` 的備份與還原（ADR-0005、ADR-0007、ADR-0008）。

> 指令行為以 `db/README.md` 為準，伺服器設定以 `docs/postgres-docker-playbook.md`（下文簡稱「Docker playbook」）為準。三者有差異時以那兩份為準，並回頭更新本文。

流程：

```
load ──► 審查 Candidate ──► promote ──► 備份 meta
  │            │
  失敗         不通過
  ▼            ▼
自動 rollback   捨棄 Candidate（6.2）
```

---

## 0. 第一次在伺服器上準備（只做一次）

前提：Docker playbook 第 2–11 節已完成，資料庫在跑、migration 已套用、角色密碼已設定。

```bash
# repo 放在 /srv/openpgx 底下
git clone https://github.com/CrowGuy/OpenPGx-Copilot.git /srv/openpgx/repo

# loader 只需要 psycopg；Ubuntu 的系統 Python 不能直接 pip install，所以用 venv
sudo apt-get install -y python3-venv
python3 -m venv /srv/openpgx/venv
/srv/openpgx/venv/bin/pip install "psycopg[binary]"
```

伺服器上也要有 `psql` client，照 Docker playbook 第 10.1 節安裝。

`etl_writer` 的密碼放進 `~/.pgpass`，之後的指令都不用輸入密碼，密碼也不會出現在指令或環境變數裡：

以**執行 loader 的那個帳號**執行，不要加 `sudo`：

```bash
sudo -v                                           # 先完成 sudo 驗證，否則下一行可能讀到空密碼
pw=$(sudo cat /srv/openpgx/secrets/etl_writer)
test -n "$pw" && printf '10.0.201.134:5432:openpgx:etl_writer:%s\n' "$pw" > ~/.pgpass
unset pw
chmod 600 ~/.pgpass                               # 權限比 600 寬時，libpq 會忽略整個檔案
psql -w -d openpgx -U etl_writer -h 10.0.201.134 -c 'SELECT current_user, inet_client_addr() AS seen_as;'
```

- 驗證用 `-w`（不詢問密碼），行為和 loader 一樣：應該看到 `etl_writer` 與 `172.30.0.1`。出現 `fe_sendauth: no password supplied` 代表 loader 讀不到 `~/.pgpass`：檔案不在這個帳號的家目錄、權限太寬，或密碼欄位是空的（`awk -F: '{print NR": user="$4" 密碼長度="length($5)}' ~/.pgpass` 檢查）。
- 這裡用 `>` 覆寫。`~/.pgpass` 裡如果還有其他服務的密碼，改用編輯器只換掉 `etl_writer` 那一行；重複用 `>>` 附加會留下舊的錯誤行，而 libpq 用的是第一個符合的那一行。

- `10.0.201.134` 換成伺服器實際的內網 IP（Docker playbook 第 6 節）。
- loader 從伺服器本機連線，走 `pg_hba.conf` 的 Docker 閘道規則，只有 `etl_writer` 能這樣連（Docker playbook 第 11.2 節）。
- 之後換了 `etl_writer` 的密碼，要同步修改 `~/.pgpass` 那一行。

---

## 1. 每次換版先設定 shell

每開一個新的 shell 都要重新執行一次。`REL` 換成這次要載入的 Release：

```bash
export REL=r2026-08-22
export REPO=/srv/openpgx/repo
export SNAP=/srv/openpgx/raw/gwas_catalog/$REL
export SCHEMA=gwas_${REL//-/_}            # gwas_r2026_08_22
export PY=/srv/openpgx/venv/bin/python
export PGHOST=10.0.201.134 PGPORT=5432 PGDATABASE=openpgx PGUSER=etl_writer PGSSLMODE=require
cd "$REPO"
```

更新程式與 migration：

```bash
git pull --ff-only
git status --short          # 應該沒有任何輸出
```

`git pull` 帶進新的 `db/migrations/*.sql` 時，照 Docker playbook 第 9.1 節重新套用（`REPO` 用上面的值）。

---

## 2. 狀態總覽

每個步驟前後都可以用這個查詢確認狀態：

```bash
psql -v ON_ERROR_STOP=1 <<'SQL'
-- 每個 Release 的狀態，以及 schema 還在不在
SELECT release_id, status, approved_by, approved_at,
       to_regnamespace('gwas_' || replace(release_id, '-', '_')) IS NOT NULL AS schema_exists
FROM meta.release ORDER BY release_id;
-- 沒有 meta 紀錄的 Release schema（應該沒有任何一列）
SELECT nspname AS schema_without_meta FROM pg_namespace
WHERE nspname ~ '^gwas_r[0-9]{4}_[0-9]{2}_[0-9]{2}$'
  AND nspname NOT IN (SELECT 'gwas_' || replace(release_id, '-', '_') FROM meta.release);
-- gwas 的 view 指向哪個 Release schema（應該只有 Active Release 一列）
SELECT DISTINCT table_schema AS gwas_points_to FROM information_schema.view_table_usage WHERE view_schema = 'gwas';
SQL
```

---

## 3. Load

### 3.1 載入前檢查

```bash
test -f "$SNAP/_SUCCESS" && echo OK                          # RawSnapshot 已完整發布
git status --short raw/gwas_catalog/contracts                # 應該沒有任何輸出
git rev-parse --short HEAD                                   # 記下來，寫進 issue
```

- RawSnapshot 依 `docs/gwas-raw-snapshot-playbook.md` 建立，正式存放在 `/srv/openpgx/raw/`（ADR-0008）。
- CurationContract 必須是 commit 過的版本，commit 也要記下來：`meta` 只記錄 CurationContract 的 sha256，之後 rebuild 要在同一個 commit 上執行，才能找回同一份 CurationContract 與同一版 loader（第 6.5 節）。沒有 commit 的修改找不回來。

### 3.2 執行

associations 全量資料要跑很久。SSH 斷線會中斷 load（會自動 rollback，不會留下半套資料，但要重跑），所以在 `tmux` 裡執行：

```bash
tmux new -s etl            # 斷線後用 tmux attach -t etl 接回
```

**進入 tmux 之後，先重新執行第 1 節。** tmux 是一個新的 shell，tmux 外面 `export` 的變數不一定會帶進來。下面第一行會在變數沒設定時直接停下來：

```bash
: "${PY:?PY 沒有設定：先在這個 shell（包括 tmux 裡）執行第 1 節}" "${SNAP:?SNAP 沒有設定：先執行第 1 節}"
time "$PY" tools/gwas_release_loader.py load \
  --snapshot-dir "$SNAP" \
  --curation-contract raw/gwas_catalog/contracts/gwas_curation_contract.json \
  --dataset-contract raw/gwas_catalog/contracts/gwas_dataset_contract.json
echo "exit=$?"
```

成功時：

- 依序印出 4 行 `Load report for published_studies|published_associations|published_ancestries|trait_mappings: {...}`。
- 最後印出 `Loaded r2026-08-22 into gwas_r2026_08_22 as candidate` 與 schema 名稱，`exit=0`。
- 把 `time` 的 `real` 記在 issue，作為之後估算換版時間的依據。

失敗時印出 `ERROR: ...`、`exit=2`，整個 load 已經 rollback，見第 6.1 節。

---

## 4. 審查 Candidate

Candidate 不是正式資料：團隊預設查詢的 `gwas` view 還指向前一個 Active Release（或第一次換版時還沒有任何 view）。審查的目的是在 Promote 之前，確認這次載入沒有因為來源改版或 loader 問題而大量丟資料。

把 4.1–4.3 的輸出貼到 issue，審查結論也寫在那裡。

### 4.1 來源紀錄

```bash
psql -v ON_ERROR_STOP=1 -x -c "SELECT release_id, status, created_at, manifest_sha256, curation_contract_version, curation_contract_sha256, genome_build FROM meta.release WHERE release_id = '$REL'"
sha256sum raw/gwas_catalog/contracts/gwas_curation_contract.json   # 應該等於 curation_contract_sha256
```

`status` 應該是 `candidate`。

### 4.2 和上一個 Release 比對列數與拒絕率

和目前的 Active Release 逐一比對各資料集。第一次換版沒有 Active Release，`prev_*` 欄位是空的：

```bash
psql -v ON_ERROR_STOP=1 <<SQL
SELECT d.key AS dataset,
       (p.load_report -> d.key ->> 'source_rows')::bigint AS prev_source_rows,
       (d.value ->> 'source_rows')::bigint AS source_rows,
       (p.load_report -> d.key ->> 'loaded_rows')::bigint AS prev_loaded_rows,
       (d.value ->> 'loaded_rows')::bigint AS loaded_rows,
       (p.load_report -> d.key ->> 'rejected_rows')::bigint AS prev_rejected,
       (d.value ->> 'rejected_rows')::bigint AS rejected,
       round((p.load_report -> d.key ->> 'rejected_ratio')::numeric, 6) AS prev_ratio,
       round((d.value ->> 'rejected_ratio')::numeric, 6) AS ratio,
       (d.value ->> 'rejection_threshold')::numeric AS threshold
FROM meta.release c
CROSS JOIN jsonb_each(c.load_report) d
LEFT JOIN meta.release p ON p.status = 'active'
WHERE c.release_id = '$REL'
ORDER BY d.key;
SQL
```

### 4.3 拒絕原因與設成空值的欄位

```bash
psql -v ON_ERROR_STOP=1 <<SQL
SELECT r.release_id, d.key AS dataset,
       d.value -> 'rejection_reasons' AS rejection_reasons,
       d.value -> 'nulled_values' AS nulled_values,
       d.value -> 'trait_uri_invalid_rows' AS trait_uri_invalid_rows
FROM meta.release r CROSS JOIN jsonb_each(r.load_report) d
WHERE r.release_id = '$REL' OR r.status = 'active'
ORDER BY dataset, r.release_id;
SQL
```

Rejected Row 本身存在 Candidate 的 schema 裡，可以逐列看原因與原始值：

```bash
psql -v ON_ERROR_STOP=1 -c "SELECT source_file, source_line, source_column, reason, left(value, 80) AS value FROM $SCHEMA.rejected_row ORDER BY source_file, source_line LIMIT 50"
```

### 4.4 抽查內容

例如 rs671 的 Association：

```bash
psql -v ON_ERROR_STOP=1 -c "SELECT a.association_id, a.study_accession, a.disease_trait, a.p_value_text FROM $SCHEMA.association_snp s JOIN $SCHEMA.association a USING (association_id) WHERE s.rsid = 'rs671' LIMIT 10"
```

### 4.5 判斷

下列每一項都沒問題，或者已經在 issue 寫下原因，才 Promote：

- [ ] 4.1 的 `curation_contract_sha256` 等於 repo 中 commit 過的 CurationContract。
- [ ] 每個資料集的 `ratio` 都明顯低於 `threshold`。超過 `threshold` 的話 load 本來就會失敗；接近 `threshold` 代表來源可能改了格式。
- [ ] 和上一個 Release 相比，`ratio` 沒有明顯上升，4.3 沒有出現新的拒絕原因或新的空值欄位。
- [ ] `source_rows` 與 `loaded_rows` 沒有減少。GWAS Catalog 通常只增不減，減少或大幅跳動要先找到原因。
- [ ] 4.3 的 Rejected Row 原因看得懂，而且是來源本身的問題，不是 CurationContract 寫錯。
- [ ] 4.4 抽查的資料合理。

**`r2026-08-22`（第一次換版）的預期**：沒有上一個 Release 可以比對；associations 的 Rejected Row 約 1 列（#12）。差很多就不要 Promote，先查原因。

不通過時見第 6.2 節。

---

## 5. Promote

`--approved-by` 填審查者的名字，會永久記在 `meta.release`：

```bash
"$PY" tools/gwas_release_loader.py promote --release "$REL" --approved-by "<審查者的名字>"
echo "exit=$?"
```

成功時印出 `Promoted r2026-08-22 to Active Release by ...; dropped schemas: [...]`，`exit=0`。

- 在同一個 transaction 內：前一個 Active Release 改成 `retired`，`gwas` 的 view 改指向這個 Release，最近 Promote 過的 3 個 Release 以外的 `retired` schema 會被刪除（`dropped schemas` 列出刪了哪些；`meta` 紀錄保留，需要時用 rebuild 重建）。
- 失敗時什麼都不會改變，見第 6.3 節。

### 5.1 確認

在伺服器上執行第 2 節的狀態總覽：這個 Release 是 `active`，`gwas_points_to` 只有 `gwas_r2026_08_22`。

再從**內網的另一台機器**用團隊成員的身分查詢（伺服器本機不能用 `analyst_ro` 連線，見 Docker playbook 第 11.2 節）：

```bash
psql "host=10.0.201.134 port=5432 dbname=openpgx user=analyst_ro sslmode=require" \
  -c "SELECT a.association_id, a.study_accession, a.disease_trait, a.p_value_text FROM gwas.association_snp s JOIN gwas.association a USING (association_id) WHERE s.rsid = 'rs671' LIMIT 10"
```

### 5.2 立刻備份 `meta`

核准紀錄重建不回來（ADR-0008）。排程每個月才備份一次，**Promote 後一定要馬上備份**，這一步不能跳過：

```bash
sudo /srv/openpgx/backup-meta.sh            # 最後一行是 ... OK backups/meta-....dump ... bytes
```

`backup-meta.sh` 不在 repo 裡，是照 Docker playbook 第 12 節在伺服器上建立的。出現 `command not found` 代表還沒建立（或沒有執行權限），先照第 12 節建立。

---

## 6. 失敗復原

| 看到的狀況 | 去哪一節 |
|---|---|
| load 印出 `ERROR: ...` | 6.1 |
| `ERROR: Release r... already exists in meta.release; Releases are never reloaded` | 6.2 |
| 審查不通過 | 6.2 |
| promote 印出 `ERROR: r... is not a candidate Release` 或其他錯誤 | 6.3 |
| Promote 之後才發現問題 | 6.4 |
| 狀態總覽中 `active` 或 `retired` 的 Release `schema_exists` 是 `f` | 6.5 |
| rebuild 印出 `ERROR: ... does not match ...` | 6.6 |
| 連線被拒（`pg_hba.conf rejects connection`、`password authentication failed`） | Docker playbook 第 15 節 |

### 6.1 Load 失敗

load 在單一 transaction 內執行，任何錯誤（包括 SSH 斷線、Ctrl-C）都會 rollback：`meta.release` 沒有這個 Release 的紀錄，schema 也不存在。用第 2 節確認後，依錯誤訊息修正原因再重跑第 3.2 節：

| 錯誤訊息 | 原因 |
|---|---|
| `Snapshot has no _SUCCESS marker`、`does not match manifest.json`、`Manifest file is absent` | RawSnapshot 不完整或被改過。不要修改已發布的 snapshot，依 `docs/gwas-raw-snapshot-playbook.md` 處理 |
| `header does not match DatasetContract expected_header`、`format_version ... does not match` | 來源改版。照 Review Required 流程更新 DatasetContract／CurationContract |
| `Rejected Row ratio ... exceeds Rejection Threshold` | 拒絕列太多。往上看同一個資料集的 `Load report for ...` 那一行的 `rejection_reasons` 找原因；不要直接調高 threshold |
| `duplicate ...` | 違反 `unique` 規則，來源出現重複的鍵 |
| `Malformed CurationContract: ...` | CurationContract 格式錯誤 |

### 6.2 審查不通過：捨棄 Candidate

同一個 Release 不能再 load 一次。審查不通過、修正之後要重新 load，必須先捨棄這個 Candidate：刪掉它的 `meta` 紀錄與 schema。Candidate 沒有核准紀錄，所以可以刪；**`active` 和 `retired` 的紀錄絕對不能刪**（ADR-0008），下面的指令會檢查狀態，不是 `candidate` 就什麼都不做。

先確認 4.1–4.3 的輸出已經貼在 issue，`echo $REL` 確認是要捨棄的 Release（不是的話先執行第 1 節），再執行：

```bash
psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
DECLARE rel text := '$REL';
BEGIN
  DELETE FROM meta.release WHERE release_id = rel AND status = 'candidate';
  IF NOT FOUND THEN
    RAISE EXCEPTION '% is not a candidate Release; nothing changed', rel;
  END IF;
  EXECUTE format('DROP SCHEMA IF EXISTS %I CASCADE', 'gwas_' || replace(rel, '-', '_'));
END \$\$;
SQL
```

看到 `DO` 就是成功。用第 2 節確認這個 Release 已經不在，再重跑第 3 節。

### 6.3 Promote 失敗

promote 在單一 transaction 內執行，失敗時狀態、view 與 schema 都沒有改變。`is not a candidate Release` 表示 `--release` 打錯，或這個 Release 不是 `candidate`（例如已經 Promote 過）；用第 2 節確認。`gwas_r... does not exist` 表示這個 Candidate 的 schema 已經不在，照第 6.2 節捨棄後重新 load。

### 6.4 Promote 之後才發現問題

目前**沒有**工具可以把 Active Release 換回前一個：promote 只接受 `candidate`。不要手動修改 `meta.release` 或 `gwas` 的 view。

- 前一個 Release 的 schema 還在（最近 Promote 過的 3 個都會保留），團隊成員可以暫時直接查詢它，例如 `gwas_r2026_07_xx.association`。
- 在 issue 記錄問題，通知負責人。

### 6.5 Release schema 不見了：Rebuild

`meta` 有紀錄、schema 卻不在的 Release，用 `rebuild` 從 RawSnapshot 重建（`db/README.md` 的「Rebuild」一節）。常見原因：還原 `meta` 之後（第 7.3 節），或 Promote 刪掉了舊 Release 的 schema。**不要刪掉 `meta` 紀錄再 load**：核准紀錄會因此遺失。

先執行第 1 節，把 `REL` 設成要重建的 Release。rebuild 必須用和當初 load 相同的 CurationContract 與 loader，所以在當初 load 時的 commit（第 3.1 節記下的）上執行：

有記下 commit 的話（`abc1234` 換成記下的值）：

```bash
COMMIT=abc1234
```

沒有記錄的話，用 load 時間推算：`main` 上在 `created_at` 之前的最後一個 commit：

```bash
git fetch && COMMIT=$(git rev-list -1 --before="$(psql -At -c "SELECT to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') || ' +0000' FROM meta.release WHERE release_id = '$REL'")" origin/main)
echo "$COMMIT"
```

接著重建：

```bash
git worktree add "/tmp/openpgx-$REL" "$COMMIT"
cd "/tmp/openpgx-$REL"
"$PY" tools/gwas_release_loader.py rebuild --release "$REL" \
  --snapshot-dir "$SNAP" \
  --curation-contract raw/gwas_catalog/contracts/gwas_curation_contract.json
echo "exit=$?"
cd "$REPO" && git worktree remove "/tmp/openpgx-$REL"
```

成功時印出 `Rebuilt r2026-08-22 (active|retired) into gwas_r2026_08_22`，`exit=0`。用第 2 節確認 `schema_exists` 變成 `t`；重建的是 Active Release 時，`gwas_points_to` 也會指回它。

- rebuild 在單一 transaction 內執行，`meta` 的狀態與核准紀錄不變；任何檢查失敗都會 rollback。
- 一次重建一個 Release。從空資料庫還原時先重建 Active Release，團隊才查得到資料；其他 Release 需要時再重建。
- 最近 Promote 過的 3 個以外的 `retired` Release，重建後只保留到下一次 Promote。不要拿它當長期依賴（例如 Release Pin）。

### 6.6 Rebuild 失敗

| 錯誤訊息 | 原因與處理 |
|---|---|
| `RawSnapshot manifest sha256 ... does not match` | `$SNAP` 不是當初 load 的那份 RawSnapshot。從第二個儲存位置找回原本的 snapshot（第 7.4 節） |
| `CurationContract version/sha256 ... does not match` | `COMMIT` 的 CurationContract 不是當初那份。用 `git log --oneline origin/main -- raw/gwas_catalog/contracts/gwas_curation_contract.json` 找出 load 前後的版本，換 `COMMIT` 再試 |
| `Rebuilt ... does not match its load report in meta.release: ...` | 同樣的輸入整理出不同的列數，代表 loader 在 load 之後改過。已經 rollback；換成更接近 load 時間的 `COMMIT` 再試 |
| `... already exists; rebuild only restores a dropped Release schema` | schema 還在，不需要重建 |
| `... is not an active or retired Release in meta.release` | `candidate` 不會失去 schema；load 失敗的 Release 沒有 `meta` 紀錄，照第 3 節重新 load |
| `... has no recorded RawSnapshot manifest, CurationContract or load report` | 這個 Release 是在 #6 之前載入的，無法驗證輸入，不能重建 |

換過 `COMMIT` 之後，先 `cd "$REPO" && git worktree remove "/tmp/openpgx-$REL"` 再重新執行第 6.5 節。

---

## 7. 備份與還原

依 ADR-0008：只備份 `meta`（核准紀錄重建不回來）；Release schema 不備份，用 rebuild 重建；RawSnapshot 要另外保存。

### 7.1 備份 `meta`

腳本與 cron 的設定見 Docker playbook 第 12 節：每個月 1 號自動備份一次，保留約一年。`meta` 只在 load 與 Promote 時改變，所以排程只是保險，**每次 Promote 後立刻手動備份一次**（第 5.2 節）才是主要的備份。

腳本失敗時不會通知任何人，每次換版前都確認一次：

```bash
tail -5 /srv/openpgx/backups/backup.log          # 最後一行應該是近期的 OK
ls -lt /srv/openpgx/backups/ | head -3           # 最新的備份應該是上次 Promote 或本月 1 號
```

### 7.2 還原到原本的資料庫

`meta` 被誤改或誤刪、資料庫本身沒事時：

```bash
cd /srv/openpgx
ls -lt backups/meta-*.dump | head                # 選要還原的備份
sudo docker compose exec -T -u postgres db pg_restore -d openpgx --clean --if-exists \
  < backups/meta-YYYYMMDD-HHMMSS.dump
```

`meta` 會回到備份當時的樣子，Release schema 和 `gwas` 的 view 不受影響。還原之後執行第 2 節（要先執行第 1 節設定連線）檢查兩者是否一致：

- 備份之後才 load 的 Release，會出現在 `schema_without_meta`。
- 備份之後才 Promote 的 Release，在 `meta` 中還是 `candidate`，但 `gwas_points_to` 已經指向它。

出現這兩種情況時不要自己修，在 issue 記錄狀態總覽的輸出，通知負責人。

### 7.3 還原到全新的空資料庫

換機器、major 版本升級、volume 遺失時，依序：

1. 照 Docker playbook 第 9.1 節套用 migration，再照第 5 節設定角色密碼。備份檔只有 `meta`，不含角色、授權與 `gwas` schema。
2. 照 7.2 執行 `pg_restore`。
3. 執行第 2 節：`meta` 的紀錄都在，但所有 `schema_exists` 都是 `f`，`gwas` 也沒有 view，團隊查不到資料。
4. 照第 6.5 節先 rebuild Active Release，`gwas` 的 view 會一起建回來；其他 Release 需要時再重建。

**沒有演練過的還原等於沒有備份。** 每次 `meta` 的結構改變（新的 migration）之後，至少在測試環境演練一次 7.3。

### 7.4 RawSnapshot

`/srv/openpgx/raw/` 是 rebuild 的唯一來源，EBI 不保證舊的 Source Release 會一直保留。同步到第二個儲存位置這件事在 ADR-0008 還沒有決定；決定之後補在這一節。在那之前，`/srv/openpgx/raw/` 底下已發布的 snapshot 絕對不能刪除或修改。
