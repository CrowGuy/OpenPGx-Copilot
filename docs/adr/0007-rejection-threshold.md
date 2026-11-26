# 違反 CurationContract 的列採隔離加門檻

載入時違反 CurationContract 的列存成 Rejected Row，附上違規原因，其餘照常載入；Rejected Row 比例超過 CurationContract 定義的 Rejection Threshold 時，整個 Release 載入失敗。GWAS Catalog 必然有少量髒資料，任何違規就失敗會一直卡住流程；只隔離不設上限，則可能悄悄吞掉一次來源格式改版造成的大量錯誤。

例外：上游沒有重新產生 studies 檔時（#31、#43），新 study 的 associations 會找不到 study。一筆來源列如果唯一的違規是找不到 study，而且 `DATE ADDED TO CATALOG` 晚於 studies 檔最新日期，就是 Orphan Row：不進 Curated Layer、保留原因，但不計入 Rejection Threshold，改由 CurationContract 的 `orphan_threshold` 限制，超過時整個 Release 載入失敗。日期條件用來區分「studies 檔落後」和「studies 檔壞掉」：如果 studies 檔缺了舊的 study，那些列仍然是 Rejected Row。沒有這個例外的話，studies 檔只要停止更新，Active Release 就會一直停在舊版。

## Considered Options

- **維持嚴格、跳過這一版**：r2026-10-03 起連續三版都是這樣處理，Active Release 一直停在 r2026-08-22。
- **改用 v1.0 studies 檔**：欄位格式不同，淘汰時程也不明。
- **調高 Rejection Threshold**：其他髒資料也會一起被放過。
