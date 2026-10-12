# 資料庫角色分離，App 不直接連資料庫

資料庫角色分為：`etl_writer`（唯一能建立 Release schema 並寫入，只供載入程式使用）、`analyst_ro`（團隊成員，可讀 `gwas` 與所有 Release schema，不可寫）、`app_ro`（未來才建，供 Copilot 後端使用，只能讀它 Release Pin 的那個 Release）。未來的 web／mobile app 永遠不直接連資料庫，一律經過後端 API。
