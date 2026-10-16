# 換版總指引

適用對象：在團隊伺服器上執行換版的團隊成員。
適用範圍：從偵測新的 Source Release 到 Promote 成 Active Release 的完整順序、每一步的判斷，以及要記錄什麼。

本文只寫**順序、變數、判斷與紀錄**。每一步的指令與細節都在原本的 playbook，本文只標出章節，不重複指令：

| 簡稱 | 文件 | 負責的階段 |
|---|---|---|
| raw | `docs/gwas-raw-snapshot-playbook.md` | Discovery、建立 RawSnapshot |
| profile | `docs/gwas-profile-report-playbook.md` | Profile 報表與比對 |
| ETL | `docs/ETL-playbook.md` | Load、審查 Candidate、Promote、備份 |
| Docker | `docs/postgres-docker-playbook.md` | 資料庫與連線問題 |

```
1 開始 ─► 2 Discovery ─► 3 RawSnapshot ─► 4 Profile 比對 ─► 5 Load 與審查 ─► 6 Promote 與備份 ─► 7 收尾
              │                │                  │                  │
       no_new_release      驗證失敗          新的未涵蓋問題       失敗／不通過
              ▼                ▼                  ▼                  ▼
            結束        raw §8／§8.1，     先討論 CurationContract   ETL §6.1／§6.2
                        常見是跳過這一版
```

---

## 0. 什麼時候做、事前準備

GWAS Catalog 大約每兩週發布一次，所以大約每兩週執行一次第 1–2 步。沒有新版就到此結束。

**一次性準備**（做過就跳過）：

- Docker playbook 第 2–12 節：資料庫、連線規則、`backup-meta.sh`。
- ETL playbook 第 0 節：repo 在 `/srv/openpgx/repo`、venv、`~/.pgpass`。
- 產生 Profile 報表需要 `openpyxl`，指令需要 `jq` 與 `tmux`：

  ```bash
  /srv/openpgx/venv/bin/pip install openpyxl
  sudo apt-get install -y jq tmux
  mkdir -p /srv/openpgx/profiles /srv/openpgx/reports
  ```

- 第 4 步要和上一版的報表比對。伺服器上第一次比對前，先把本機的 `reports/gwas-profile-report-r2026-08-22.xlsx` 用 `scp` 複製到伺服器的 `/srv/openpgx/reports/`。

**每次開始前確認**：

- 沒有其他人正在換版或跑 loader。
- 磁碟空間：`df -h /srv/openpgx`，可用空間至少是上一版 snapshot（`du -sh /srv/openpgx/raw/gwas_catalog/r*/ | tail -1`）的兩倍。

---

## 1. 開始

整個換版都在同一個 tmux session 裡執行；SSH 斷線不會中斷正在跑的程式：

```bash
tmux new -s release                 # 斷線後用 tmux attach -t release 接回
export REPO=/srv/openpgx/repo PY=/srv/openpgx/venv/bin/python
cd "$REPO" && git pull --ff-only && git status --short   # 最後一個指令沒有輸出才繼續

export GWAS_RUN_DIR="/srv/openpgx/operations/gwas_catalog/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$GWAS_RUN_DIR"
export GWAS_CURRENT_MANIFEST="$(ls -d /srv/openpgx/raw/gwas_catalog/r*/ | sort | tail -1)manifest.json"

# 把變數存起來：在 tmux 開新視窗或重新登入時，用 source 載回來
cat > "$GWAS_RUN_DIR/env.sh" <<EOF
export REPO=$REPO PY=$PY GWAS_RUN_DIR=$GWAS_RUN_DIR GWAS_CURRENT_MANIFEST=$GWAS_CURRENT_MANIFEST
cd $REPO
EOF
echo "$GWAS_RUN_DIR"
```

在新的 shell 接續時：

```bash
source "$(ls -d /srv/openpgx/operations/gwas_catalog/*/ | sort | tail -1)env.sh"
```

`git pull` 帶進新的 `db/migrations/*.sql` 時，先照 Docker playbook 第 9.1 節套用。

---

## 2. Discovery

照 **raw §5.1–5.3** 執行：先驗證 current manifest，再跑 Discovery，讀 `status`。

| 結果 | 下一步 |
|---|---|
| `no_new_release` | 結束，不需要開 issue |
| `review_required`（exit 20） | 停止，照 raw §7 調查 |
| exit 2 | 修正原因（網路、設定）後重跑 Discovery |
| `candidate_ready` | 繼續 |

`candidate_ready` 時，取得這次的 Release 並存進 `env.sh`：

```bash
export REL=$(jq -r .snapshot_id "$GWAS_RUN_DIR/release-config.json")
echo "export REL=$REL" >> "$GWAS_RUN_DIR/env.sh"
echo "$REL"
```

**開換版 issue**，標題「換版 $REL」，內容用第 8 節的範本。之後每一步的結果都貼在這個 issue。

---

## 3. RawSnapshot

照 **raw §4.2** 審查 candidate（換版時也要確認 `output_root` 是 `/srv/openpgx/raw/gwas_catalog`、`minimum_data_rows` 是 contract 裡的值，`expected_column_count` 和上一版相同），接著 **raw §4.3** 建立 snapshot、**raw §4.4** 驗證。下載與驗證約需 25 分鐘。

成功後：

```bash
export SNAP=/srv/openpgx/raw/gwas_catalog/$REL
echo "export SNAP=$SNAP" >> "$GWAS_RUN_DIR/env.sh"
jq -r '.files[] | "\(.role)\t\(.metrics.data_row_count // .data_row_count)"' "$SNAP/manifest.json"   # 筆數貼到 issue
```

| 失敗訊息 | 下一步 |
|---|---|
| `VALIDATION ERROR: ... absent from published_studies` 等 cross-file 錯誤 | raw §8.1：量化影響，超過 Rejection Threshold 就**跳過這一版**（例如 #31），到第 7 步收尾 |
| 其他下載或驗證錯誤 | raw §8 |

---

## 4. Profile 比對

照 **profile 第八節**：產生報表，用 Review Queue 和上一版比對。

| 結果 | 下一步 |
|---|---|
| 沒有 `NEW` | 繼續 |
| 有 `NEW`，CurationContract 已涵蓋 | 在 issue 寫下判斷，繼續 |
| 有 `NEW`，未涵蓋，而且是 Required Field 或 High | 停止，討論是否要出新版 CurationContract |

比對輸出貼到 issue。

---

## 5. Load 與審查 Candidate

1. **ETL §1**：`REL` 已經設定，直接執行。它會另外設定 `SCHEMA` 與連線用的 `PG*` 變數。
2. **ETL §2**：狀態總覽。換版前應該只有一個 `active`。
3. **ETL §3**：載入前檢查、執行 load。記下 `git rev-parse --short HEAD` 與 `time` 的 `real`。
4. **ETL §4**：審查 Candidate。4.2 會和目前的 Active Release 比對，4.1–4.3 的輸出貼到 issue。4.4 另外確認新的 Release 有 `source_line`：

   ```bash
   psql -c "SELECT source_line, study_accession FROM $SCHEMA.study ORDER BY source_line LIMIT 3"
   ```

| 結果 | 下一步 |
|---|---|
| load 失敗 | ETL §6.1 |
| 審查不通過 | ETL §6.2 捨棄 Candidate。snapshot 保留；修正後重新 load，不需要重跑第 2–3 步 |
| 通過 ETL §4.5 的每一項 | 繼續 |

---

## 6. Promote 與備份

照 **ETL §5**：Promote、確認、**立刻備份 `meta`**（5.2，不能跳過）。

Promote 後的狀態總覽（ETL §2）應該是：

- `$REL` 是 `active`。
- 前一個 Active Release 是 `retired`，schema 仍然存在（保留最近 Promote 過的 3 個）。
- `gwas_points_to` 只有 `$SCHEMA` 一列。

從內網另一台機器用 `analyst_ro` 查詢（ETL §5.1），確認團隊成員看到的是新版。

---

## 7. 收尾

- **current manifest 不需要更新**：下次第 1 步會自動選到最新的 snapshot（raw §5.1）。
- **`.failed`**：先前被跳過的版本留下的 staging，在這次換版成功、相關 issue 都已記錄後可以刪除：`ls /srv/openpgx/raw/gwas_catalog/.failed/`。
- **Profile 與報表**：`/srv/openpgx/profiles/` 與 `/srv/openpgx/reports/` 保留這一版的結果，下次比對要用。
- **issue**：照第 8 節補齊結果。換版成功就關閉；被跳過的版本保持 open，直到下一版成功。
- **playbook**：過程中發現寫錯、沒寫到或看不懂的地方，列在 issue，換版後一起修正。

---

## 8. 換版 issue 範本

```markdown
## 換版 r<release date>

- 操作人員／日期：
- 前一個 Active Release：r…
- repo commit（ETL §3.1）：
- 結果：已 Promote／跳過（原因）／停在第 _ 步

### 2. Discovery
- status：candidate_ready
- GWAS_RUN_DIR：/srv/openpgx/operations/gwas_catalog/…

### 3. RawSnapshot
- 驗證：passed／failed（錯誤訊息）
- 各檔案筆數（和上一版比較）：

| 檔案 | 上一版 | 這一版 |
|---|---:|---:|

### 4. Profile 比對
- load_to_curated items：… -> …；High：… -> …
- NEW 項目與判斷：

### 5. Load 與審查
- load 時間（real）：
- ETL §4.2 輸出：
- ETL §4.3 新的拒絕原因或空值欄位：
- ETL §4.5 判斷：

### 6. Promote
- approved_by／時間：
- dropped schemas：
- meta 備份檔：

### Playbook 問題
- 
```

---

## 9. 決策速查

| 狀況 | 怎麼做 | 細節 |
|---|---|---|
| Discovery 是 `no_new_release` | 結束 | raw §5.3 |
| Discovery 是 `review_required` | 停止調查，可能要更新 DatasetContract | raw §7 |
| snapshot cross-file 驗證失敗 | 量化影響，超過 Rejection Threshold 就跳過這一版 | raw §8.1 |
| 同樣原因連續兩版失敗 | 開 issue 討論調整做法，不要在操作當下放寬規則 | raw §8.1 |
| Profile 出現未涵蓋的新問題 | 先不要載入，討論 CurationContract 新版 | profile 第八節 |
| load 失敗 | 看錯誤訊息，不要直接調高 threshold | ETL §6.1 |
| 審查不通過 | 捨棄 Candidate，snapshot 保留 | ETL §6.2 |
| Promote 之後才發現問題 | 沒有工具可以換回上一版；團隊暫時直接查前一個 schema | ETL §6.4 |
| 連線被拒 | 檢查 `pg_hba.conf` 與密碼 | Docker §15 |
