# 資料庫角色分離，Copilot 只讀 Rule Evidence

資料庫角色分為：`etl_writer`（唯一能建立 Release schema 並寫入，只供載入程式使用）、`analyst_ro`（團隊成員，可讀 `gwas` 與所有 Release schema，不可寫）、`app_ro`（未來才建，供 Copilot 後端使用）。Copilot 不能直接讀 Curated Layer：`app_ro` 只能讀 Rule Evidence 所在的 schema，不能讀 `gwas` 或任何 Release schema。Rule Evidence 由之後的整理流程從某個 Release Pin 的 Curated Layer 產生並經過審查。未來的 web／mobile app 永遠不直接連資料庫，一律經過後端 API。

## Consequences

- Curated Layer 的設計只需服務團隊研究者；Copilot 需要的轉換（例如排除 Risk Allele 為 `?` 的 Association）由 Rule Evidence 的整理流程負責。
