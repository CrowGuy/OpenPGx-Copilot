# p-value 存成 mantissa＋exponent，不提供 double 欄位

GWAS Catalog 的 P-VALUE 格式一律是 `mE-x`，但指數可以小到 E-28539。在 `r2026-08-22` 中，有 7,601 列超出 double 的範圍，其中 6,271 列用 double 解析會變成 0.0，失去真實大小，也讓 `p_value < 5e-8` 這類篩選悄悄出錯。因此 Curated Layer 把 p-value 存成 `p_value_mantissa`（numeric）與 `p_value_exponent`（integer），並保留原文；刻意不提供 double 型別的 p-value 欄位。顯著性篩選一律使用來源提供的 `pvalue_mlog`（-log10 p，例如 `pvalue_mlog >= 7.3` 相當於 p ≤ 5×10⁻⁸）；它和 P-VALUE 每一列都一致，而且數值範圍不會溢位。
