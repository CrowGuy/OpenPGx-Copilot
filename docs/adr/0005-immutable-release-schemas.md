# 每個 Release 一個不可變 schema，用 view 指向 Active Release

每個 Release 載入到自己的 schema（例如 `gwas_r2026_08_22`），載入完成後不再修改。另有一個 `gwas` schema，只包含指向 Active Release 的 view，團隊預設查詢這裡。Promote 在單一 transaction 內切換 view 並更新 Release Status。每個 Release 的狀態、來源 RawSnapshot manifest、CurationContract 版本、Rejected Row 比例與核准者，記錄在 `meta` schema，作為原設計 RuntimeReleaseManifest 的輕量版。Promote 時只保留最近 3 個 Promote 過的 Release 的 schema（依 Promote 時間排序），更舊的刪除，需要時從 RawSnapshot 重建。Candidate 不佔保留名額，也不會被自動刪除，這樣上一個 Active Release 一定會保留；審查不通過的 Candidate 依 ETL playbook 手動捨棄。

## Considered Options

- **單一組表加 `release_id` 欄位**：版本混在一起，切換與刪除都要逐列處理，也難以保證不可變。
- **只保留最新版**：失去 Release Pin 的能力。

## Consequences

- 未來的 Copilot 透過 Release Pin 固定使用特定 Release schema，平台換版不影響它。
- Release schema 每次都是全新建立，不需要 migration；只有 `meta` schema 需要版本化的 migration。
- 沒有 Promote 也沒有捨棄的 Candidate 會一直留著 schema；舊的 Candidate 也仍然可以在較新的 Active Release 之後被 Promote，讓 `gwas` 退回較舊的 Source Release。換版前要用狀態總覽確認，捨棄不用的 Candidate。
