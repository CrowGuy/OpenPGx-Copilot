# 資料不進 git；只備份重建不回來的部分

`raw/`、`profiles/`、`reports/` 不進 git，只 commit 程式、DatasetContract（`raw/gwas_catalog/contracts/`）與 manifest，資料可以依 manifest 重建。備份範圍依重建成本決定：

- **Release schema**：不備份，可以從 RawSnapshot 加 CurationContract 重建。
- **`meta` schema**（以及未來 Copilot 的表）：用 `pg_dump` 備份，因為核准紀錄重建不回來。`meta` 只在 load 與 Promote 時改變，所以每次 Promote 後立刻手動備份是主要的備份；cron 每月自動備份一次作為保險，保留約一年。
- **RawSnapshot**：存放在伺服器固定路徑（例如 `/srv/openpgx/raw/`），並定期同步到第二個儲存位置，因為 EBI 不保證舊的 Source Release 會一直保留。

## Open

- RawSnapshot 的第二個儲存位置（另一顆磁碟或物件儲存）尚未決定。
