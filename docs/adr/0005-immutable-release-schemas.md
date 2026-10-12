# 每個 Release 一個不可變 schema，用 view 指向 Active Release

每個 Release 載入到自己的 schema（例如 `gwas_r2026_08_22`），載入完成後不再修改。另有一個 `gwas` schema，只包含指向 Active Release 的 view，團隊預設查詢這裡。Promote 在單一 transaction 內切換 view 並更新 Release Status。每個 Release 的狀態、來源 RawSnapshot manifest、CurationContract 版本、Rejected Row 比例與核准者，記錄在 `meta` schema，作為原設計 RuntimeReleaseManifest 的輕量版。只保留最近 3 個 Release 的 schema，更舊的刪除，需要時從 RawSnapshot 重建。

## Considered Options

- **單一組表加 `release_id` 欄位**：版本混在一起，切換與刪除都要逐列處理，也難以保證不可變。
- **只保留最新版**：失去 Release Pin 的能力。

## Consequences

- 未來的 Copilot 透過 Release Pin 固定使用特定 Release schema，平台換版不影響它。
- Release schema 每次都是全新建立，不需要 migration；只有 `meta` schema 需要版本化的 migration。
