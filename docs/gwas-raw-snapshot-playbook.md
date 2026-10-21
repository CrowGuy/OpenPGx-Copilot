# GWAS Catalog Raw Snapshot 維運 Playbook

文件版本：1.0  
適用程式：`discover_gwas_release.py`、`gwas_raw_snapshot.py`  
資料契約：`gwas_dataset_contract.json`

> 整個換版流程（Discovery 到 Promote）的順序與判斷見 `docs/release-runbook.md`。本文的指令假設已設定 `REPO=/srv/openpgx/repo`、`PY=/srv/openpgx/venv/bin/python`，並在 `$REPO` 執行。

## 1. 目的與適用範圍

本文件說明如何：

- 第一次建立 GWAS Catalog immutable raw baseline。
- 後續偵測並匯入新的 GWAS Catalog release。
- 處理 filename、format、header 或資料驗證異常。
- 驗證發布結果、保留稽核資訊及安全清理 staging。

目前產品邊界如下：

- Published associations、studies、ancestries 與 trait mappings 為 `load_to_curated`。
- Unpublished studies、ancestries 為 `raw_only`；保留 raw 與 ingestion 能力，但不進入第一階段 curated evidence。
- 已發布且包含 `_SUCCESS` 的 snapshot 不可修改或覆寫。

## 2. 核心檔案與責任

| 檔案 | 用途 | 是否人工維護 |
| --- | --- | --- |
| `gwas_dataset_contract.json` | 核准的 endpoint、filename pattern、format、header、欄位數與載入政策 | 是；變更須 review |
| `discovery-report.json` | HEAD 探測、解析結果、決策原因及 contract checksum | 否；每次執行產生 |
| `release-config.json` | 某一 release 的候選下載與驗證設定 | discovery 產生，執行前人工確認 |
| `manifest.json` | 已下載檔案的來源、metrics、checksum、validation 與 pipeline provenance | 否；snapshot 程式產生 |
| `manifest.sha256` | 驗證 `manifest.json` 未被變更 | 否 |
| `validation-report.json` | file-level 與 cross-file 驗證結果 | 否 |
| `_SUCCESS` | snapshot 完整發布標記 | 否；最後才產生 |

`gwas_dataset_contract.json` 不應包含每次變動的實際 release date、最終 filename、row count 或檔案 checksum。這些值由 discovery 或 snapshot 階段產生。

## 3. 執行前提

### 3.1 環境

- Python 3.10 以上。
- 可連線至 contract 允許的 EBI host。
- `output_root` 可以是絕對或相對路徑，且執行帳號具有寫入權限。相對路徑以 **contract 檔所在的目錄**為起點，不是目前的工作目錄；正式 contract 用絕對路徑 `/srv/openpgx/raw/gwas_catalog`。
- 可用空間至少應高於預估下載量的兩倍，以容納 archive、解壓後 TSV 與 staging。
- 同一個 `snapshot_id` 同時間只能有一個執行程序。

### 3.2 執行前檢查

```bash
"$PY" -m json.tool raw/gwas_catalog/contracts/gwas_dataset_contract.json >/dev/null
"$PY" tools/discover_gwas_release.py --help >/dev/null
"$PY" tools/gwas_raw_snapshot.py --help >/dev/null
```

確認 contract 中的 `output_root` 指向正式 raw storage，例如：

```json
"output_root": "/srv/openpgx/raw/gwas_catalog"
```

建議每次執行建立獨立的操作紀錄目錄：

```bash
export GWAS_RUN_DIR="/srv/openpgx/operations/gwas_catalog/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$GWAS_RUN_DIR"
```

## 4. 第一次建立 baseline

### 4.1 執行 discovery

第一次沒有 `current-manifest`，省略該參數：

```bash
python discover_gwas_release.py \
  --contract gwas_dataset_contract.json \
  --candidate-out "$GWAS_RUN_DIR/release-config.json" \
  --report-out "$GWAS_RUN_DIR/discovery-report.json" \
  > "$GWAS_RUN_DIR/discovery-stdout.json"
```

預期結果：

- exit code 為 `0`。
- `discovery-report.json` 的 `status` 為 `candidate_ready`。
- 已產生 `release-config.json`。
- 所有 required endpoints 的 `release_date` 相同。

檢查狀態：

```bash
jq '{status, discovered_release_date, reasons, warnings}' \
  "$GWAS_RUN_DIR/discovery-report.json"
```

### 4.2 審查第一次 candidate

```bash
jq '{
  dataset,
  snapshot_id,
  declared_data_date,
  distribution_release_date,
  output_root,
  files: [.files[] | {
    role,
    filename,
    format_version,
    load_policy,
    expected_column_count,
    minimum_data_rows
  }]
}' "$GWAS_RUN_DIR/release-config.json"
```

操作人員必須確認：

- `snapshot_id` 與 `declared_data_date` 正確。
- 六個來源屬於同一 release。
- associations archive filename、內部 TSV member、format 與 Ensembl 版本正確。
- Published 為 `load_to_curated`，unpublished 為 `raw_only`。
- `expected_header` 與 `expected_column_count` 為已核准介面。
- `output_root` 是預期的正式位置。
- 若已由官方公告確認 distribution release date，可在 candidate 中補上；不確定時保留 `null`，不可猜測。

第一次沒有歷史資料，因此 discovery 只能確認「符合 contract」及「各 endpoint 彼此一致」，不能判斷相對上一版的筆數或內容變動。

### 4.3 建立 raw snapshot

```bash
"$PY" tools/gwas_raw_snapshot.py \
  --config "$GWAS_RUN_DIR/release-config.json" \
  2>&1 | tee "$GWAS_RUN_DIR/raw-snapshot.log"
```

程式會依序完成：

1. 建立唯一 staging directory 與 snapshot lock。
2. 下載為 `.part`，驗證 HTTP response 後 rename。
3. 解壓 associations archive。
4. 計算 byte size、SHA-256、header SHA-256、欄位數、筆數及 malformed row 數。
5. 執行 file-level validation。
6. 執行 published studies、associations、ancestries 的 cross-file validation。
7. 產生 `validation-report.json`、`manifest.json` 與 `manifest.sha256`。
8. 驗證 manifest checksum，建立 `_SUCCESS`。
9. 將 staging directory atomic rename 成正式 snapshot directory。

### 4.4 驗證正式發布

以下以 `r2026-08-22` 為例；實際值以 candidate 的 `snapshot_id` 為準：

```bash
export GWAS_SNAPSHOT_DIR="/srv/openpgx/raw/gwas_catalog/r2026-08-22"

test -f "$GWAS_SNAPSHOT_DIR/_SUCCESS"
test -f "$GWAS_SNAPSHOT_DIR/manifest.json"
test -f "$GWAS_SNAPSHOT_DIR/manifest.sha256"
test -f "$GWAS_SNAPSHOT_DIR/validation-report.json"

cd "$GWAS_SNAPSHOT_DIR"
sha256sum --check manifest.sha256
jq -e '.validation.status == "passed"' manifest.json >/dev/null
jq -e '.status == "passed"' validation-report.json >/dev/null
```

只有上述檢查全部成功，這份 snapshot 才算發布完成；之後的 Discovery 會自動以它為 current manifest（第 5.1 節）。

不得修改 baseline 目錄中的 TSV、manifest、checksum、validation report 或 `_SUCCESS`。

### 4.5 基準完成後強化 row-count gate

預設 contract 的 `minimum_data_rows` 為 bootstrap 值。第一份可信 baseline 建立後，應根據實際 `data_row_count` 設定合理下限，例如基準筆數的 80%，並以 reviewed contract change 提交。

門檻只用來攔截空檔或異常縮水，不應要求每次 release 與上一版筆數完全相同。

## 5. 後續 release 更新

### 5.1 選定 current manifest

`current-manifest` 是**最新一份已發布的 snapshot**：`/srv/openpgx/raw/gwas_catalog/` 底下日期最新的 `r*` 目錄。只有通過驗證、建立 `_SUCCESS` 的 snapshot 才會被 rename 成這個名稱；staging（`.staging`）與失敗的執行（`.failed`）不會被選到。不需要另外登記。

它不一定是 Active Release：snapshot 建好但 Candidate 審查不通過時，下一次 Discovery 仍然從這份比較，不會再下載同一版。

```bash
export GWAS_CURRENT_MANIFEST="$(ls -d /srv/openpgx/raw/gwas_catalog/r*/ | sort | tail -1)manifest.json"
echo "$GWAS_CURRENT_MANIFEST"

test -f "$(dirname "$GWAS_CURRENT_MANIFEST")/_SUCCESS"
cd "$(dirname "$GWAS_CURRENT_MANIFEST")"
sha256sum --check manifest.sha256
cd "$REPO"
```

### 5.2 執行 discovery

```bash
"$PY" tools/discover_gwas_release.py \
  --contract raw/gwas_catalog/contracts/gwas_dataset_contract.json \
  --current-manifest "$GWAS_CURRENT_MANIFEST" \
  --candidate-out "$GWAS_RUN_DIR/release-config.json" \
  --report-out "$GWAS_RUN_DIR/discovery-report.json" \
  > "$GWAS_RUN_DIR/discovery-stdout.json"; echo "exit=$?"
jq -r .status "$GWAS_RUN_DIR/discovery-report.json"
```

### 5.3 依 discovery 狀態處理

| 狀態 | Exit code | 意義 | 操作 |
| --- | ---: | --- | --- |
| `candidate_ready` | 0 | 發現日期較新的 release，且符合 contract | 審查 candidate，通過後執行 snapshot |
| `no_new_release` | 0 | release date 與 current 相同，metadata 未見變更 | 結束本次操作，不執行下載 |
| `review_required` | 20 | pattern、format、Ensembl、日期一致性或同日期 metadata 發生異常 | 停止，不產生 snapshot；依第 7 節調查 |
| operational/config error | 2 | 網路、HTTP、JSON 或設定錯誤 | 修復原因後重跑 discovery |
| interrupted | 130 | 人工中斷 | 確認執行狀態後再重跑 |

不要只依 exit code `0` 判斷需要下載；必須讀取 `status`，因為 `candidate_ready` 與 `no_new_release` 都是 exit code `0`。

### 5.4 審查與發布新 release

當狀態為 `candidate_ready`：

1. 執行與第一次相同的 candidate review。
2. 確認新 `declared_data_date` 晚於 current manifest。
3. 確認正式 snapshot directory 尚不存在。
4. 執行 `gwas_raw_snapshot.py`。
5. 執行發布後 checksum、validation 與 `_SUCCESS` 驗證。
6. 不需要登記 current manifest：新的 snapshot 是日期最新的 `r*` 目錄，下一次第 5.1 節會自動選到它。
7. 保留舊 snapshot；不得刪除或覆寫。

## 6. Snapshot 驗證範圍

### 6.1 File-level validation

每份 TSV 至少檢查：

- 檔案非空。
- `data_row_count >= minimum_data_rows`。
- UTF-8 可解析。
- 每個 physical row 欄位數與 header 一致。
- header 欄位無重複。
- `expected_column_count` 一致。
- 完整 header 順序與 `expected_header` 一致。

末行沒有 newline 為 warning，不會單獨阻止發布。

### 6.2 Cross-file validation

Published core 三份檔案必須一起存在，並檢查：

- `published_studies.STUDY ACCESSION` 不可重複或空白。
- associations、ancestries 的 study accession 不可空白。
- associations、ancestries 不可引用 studies 中不存在的 accession。
- studies 的 `ASSOCIATION COUNT` 必須是非負整數。
- 宣告的 association count 必須與 associations 實際筆數一致。
- associations 最新的 `DATE ADDED TO CATALOG` 不可比 studies 新。兩個日期寫在 `metrics` 的 `published_studies_latest_date_added` 與 `published_associations_latest_date_added`。

Published study 沒有 ancestry row 目前列為 warning；其他上述不一致為 error。

## 7. `review_required` 處理流程

收到 `review_required` 時，不可直接放寬 regex、移除 header 驗證或覆寫既有 snapshot。先保存並閱讀：

```bash
jq '{status, discovered_release_date, reasons, warnings, endpoints}' \
  "$GWAS_RUN_DIR/discovery-report.json"
```

### 7.1 新 release 的 filename、format、Ensembl 或 schema 改變

1. 從 report 記錄官方回傳 filename、Content-Disposition、Content-Length 與有效 URL。
2. 在與正式 `output_root` 分離的 inspection directory 下載樣本或完整檔案。
3. 比較 archive member、完整 header、欄位語意及 identifier 格式。
4. 評估 parser、curated schema、cross-file validation 與下游應用是否需要修改。
5. 經 code review 核准後，更新 contract／程式及版本。
6. 重新執行 discovery；只有回到 `candidate_ready` 才能進入正常發布流程。

Ensembl 版本變更可能改變 variant-to-gene mapping，不能只修改 `expected_ensembl` 後直接發布。

### 7.2 同一 release date 的來源 metadata 改變

這可能代表上游原地替換檔案。處理原則：

- 保留既有 immutable snapshot。
- 保存 discovery report，記錄 filename、Content-Length 或 ETag 差異。
- 不將同日期的新內容覆寫到既有 snapshot。
- 由資料治理／工程負責人決定是否建立明確 revision，例如 `rYYYY-MM-DD-rev2`。
- Revision 必須使用經核准的獨立 config 與稽核紀錄，不屬於例行自動更新。

### 7.3 發現日期早於 current manifest

停止操作，檢查 endpoint 是否回退、current manifest 是否選錯、時區／日期解析是否異常。不得用舊 release 取代 current。

## 8. Raw snapshot 失敗與復原

`gwas_raw_snapshot.py` exit code：

| Exit code | 意義 |
| ---: | --- |
| 0 | 發布成功 |
| 2 | 已知的設定、下載、validation 或發布錯誤 |
| 1 | 未預期錯誤 |
| 130 | 人工中斷 |

失敗時程式會保留唯一的 staging directory 供檢查，並釋放正常流程建立的 lock。優先檢查：

- 操作 log。
- staging 中的 `.part` 是否表示下載未完成。
- `validation-report.json` 的 errors 與 warnings。
- 實際 header、欄位數與 malformed row。
- `.locks/<snapshot_id>.lock` 是否因程序被強制終止而殘留。

若正式 snapshot directory 已存在，程式會拒絕覆寫。不要刪除正式 snapshot 來讓重跑成功；應先確認是否已完成發布，或改用經核准的新 snapshot revision。

### 8.1 Cross-file validation 失敗：來源資料不一致

例如 `published_associations contains study accessions absent from published_studies`。這是官方發布的檔案彼此對不上，不是下載或程式錯誤；重跑不會改善。下載的檔案留在 staging，直接用來量化影響，不需要重新下載。

若同時出現 `published_studies appears stale: latest DATE ADDED TO CATALOG <studies 日期> < published_associations <associations 日期>`，表示上游這一版沒有重新產生 studies 檔，內容停在較舊的版本，所以 associations 新加入的 study 都找不到（r2026-10-03 即是如此，見 #31）。這是上游的問題，重跑不會改善。

量化影響：

```bash
ST=/srv/openpgx/raw/gwas_catalog/.staging/<log 裡的 staging 目錄>
cd "$ST"
A=$(find . -name 'gwas-catalog-download-associations-alt-full.tsv')
S=$(find . -name 'gwas-catalog-v1.0.3.1-studies-r*.tsv')
col(){ head -1 "$1" | tr '\t' '\n' | grep -nx "$2" | cut -d: -f1; }
sa=$(col "$S" 'STUDY ACCESSION'); aa=$(col "$A" 'STUDY ACCESSION')
awk -F'\t' -v s="$sa" -v a="$aa" 'FNR==1{next} NR==FNR{ok[$s]=1;next} !($a in ok){print $a}' "$S" "$A" \
  | sort | uniq -c | sort -rn > "$GWAS_RUN_DIR/missing-studies.txt"
awk '{r+=$1} END{print "rows="r, "studies="NR}' "$GWAS_RUN_DIR/missing-studies.txt"
```

判斷：

- 受影響的列數超過 CurationContract 的 Rejection Threshold（associations 資料列的 0.1%）：**跳過這一版**，等下一個 Source Release。放寬 RawSnapshot 的檢查也沒用，load 時一樣會超過門檻。
- 不要為了單一版本調高 Rejection Threshold 或修改驗證規則。
- **連續跳過最多 2 版**（#31 決定）：
  - r2026-10-03 算第 1 次跳過；下一版若同樣原因失敗算第 2 次，照樣跳過。
  - 第 3 版仍然因同樣原因失敗時，開 issue 決定備案的細節，不要在操作當下自行放寬。方向見 #31：孤兒列像 Rejected Row 一樣保留來源列與原因，但不計入 Rejection Threshold，改用獨立上限；這會偏離 ADR-0007 的單一 Rejection Threshold，屆時一併修改 ADR-0007 與 CurationContract。
  - 「同樣原因」：cross-file validation 出現孤兒列（associations 或 ancestries 的 study 不在 studies 檔裡），或 `published_studies appears stale` 檢查失敗。其他失敗照第 7 節 `review_required` 流程處理，不計入跳過次數。
  - 中間只要有任何一版換版成功，計數就歸零。

跳過時：

1. 把 `validation-report.json` 複製到 `$GWAS_RUN_DIR`，連同 `missing-studies.txt` 一起保留。
2. 照第 9.1 節把 staging 移到 `.failed`；下一版成功換版後可刪除。
3. 開 issue 記錄跳過的 release、受影響列數與判斷（例如 #31）。
4. `GWAS_CURRENT_MANIFEST` 不變。下一次 Discovery 會直接找到最新的 release，被跳過的版本不需要處理。

## 9. Staging 與 lock 清理

### 9.1 何時可處理 staging

只有同時符合下列條件才可處理：

- 已確認沒有 `gwas_raw_snapshot.py` 正在執行。
- staging 對應執行已確定失敗或被中斷。
- 已保存需要的 log、validation report 與調查證據。
- 該 staging 不是唯一需要保留的 incident evidence。

建議先移至 quarantine，而不是立即刪除：

```bash
mkdir -p /srv/openpgx/raw/gwas_catalog/.failed
mv /srv/openpgx/raw/gwas_catalog/.staging/r2026-08-22-<run-id> \
  /srv/openpgx/raw/gwas_catalog/.failed/
```

依組織 retention policy 到期後再刪除 quarantine。成功發布時 staging 已被 atomic rename 成正式 snapshot，不需要另外清理。

### 9.2 殘留 lock

先確認沒有執行中的程序，再檢查 lock 內容與對應 staging。只有能證明 lock 已失效時，才可移除單一明確 lock file。不得批次清空 `.locks`。

## 10. 完成條件與交接紀錄

每次成功更新應記錄：

- 執行時間與操作人員。
- 舊、新 snapshot ID。
- contract Git revision 或 SHA-256。
- discovery report 路徑。
- release config 路徑。
- snapshot log 路徑。
- manifest 路徑與 manifest SHA-256。
- validation 結果與 warnings。
- contract、schema 或 pipeline 是否有變更及其 review reference。

操作完成的最低標準：

- 正式 snapshot directory 存在。
- `_SUCCESS` 存在。
- `manifest.sha256` 驗證成功。
- manifest 與 validation report 的狀態均為 `passed`。
- 舊 snapshot 保持不變且仍可讀取。

## 11. 快速操作清單

### 第一次下載

- [ ] 驗證 contract 與 `output_root`。
- [ ] 不帶 `--current-manifest` 執行 discovery。
- [ ] 確認 `candidate_ready` 並人工審查 candidate。
- [ ] 執行 raw snapshot。
- [ ] 驗證 `_SUCCESS`、manifest checksum 與 validation。
- [ ] 依 baseline 筆數 review `minimum_data_rows`。

### 後續更新

- [ ] 驗證 current snapshot 的 `_SUCCESS` 與 checksum。
- [ ] 帶 `--current-manifest` 執行 discovery。
- [ ] `no_new_release`：結束。
- [ ] `review_required`：停止並依第 7 節調查。
- [ ] `candidate_ready`：審查 candidate 後執行 raw snapshot。
- [ ] 驗證新 snapshot（它會自動成為下一次的 current manifest）。
- [ ] 保留所有舊 snapshot 與操作紀錄。
