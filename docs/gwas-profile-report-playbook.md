# Gwas Profile Report xlsx file

先建立一個核心觀念：這份 Excel 不是 raw TSV 本身，而是 raw snapshot 的「欄位級觀察報告」。

它包含三層資訊：

1. 客觀事實：筆數、NULL 數、unique count、長度、parse failure。
2. 程式推測：candidate datatype、delimiter、priority、review flags。
3. 人工決策：黃色欄位中的 Approved、Decision、Status、Reviewer。

只有第 1 層可以直接當成 profiling 結果；第 2 層不能直接變成 ETL 規則。

## 一、先讀 Overview

這份報告分析的是 `r2026-08-22`：

| Role                   |        筆數 | 第一階段用途          |
| ---------------------- | --------: | --------------- |
| published_associations | 1,191,572 | load_to_curated |
| published_studies      |   229,900 | load_to_curated |
| published_ancestries   |   298,269 | load_to_curated |
| trait_mappings         |   110,339 | load_to_curated |
| unpublished_studies    |    14,193 | raw_only        |
| unpublished_ancestries |    30,657 | raw_only        |

其他重點：

* 共 126 個欄位。
* unique count 已用 exact profiling 覆蓋，不再是 HyperLogLog 估算。
* 173 個 review items：

  * High：13
  * Medium：69
  * Low：91
* 目前 173 項全部都是 `Pending`。

依照目前產品邊界，先處理四個 `load_to_curated` role；unpublished 只保留 raw，不必納入第一階段的 curated contract 決策。

如果 Overview 的 Review Status 數字是空白，通常是 Excel `COUNTIF` 尚未重算。用 Excel 或 LibreOffice 開啟後重新計算即可；`Review Queue` 才是權威明細。

## 二、Column Summary：欄位總覽

這是最重要的入口。每列代表一個 `Role + Column`。

建議先篩選：

```text
Role 不包含 unpublished
Priority = High
```

然後再看 Medium、Low。

### 主要欄位解讀

| 欄位                    | 意義                                      |
| --------------------- | --------------------------------------- |
| Strict Null %         | 空字串加上只有空白字元的比例                          |
| Candidate Null %      | `NA`、`NR`、`N/A`、`Unknown` 等候選 token 的比例 |
| Raw Unique            | 原始字串的 distinct count                    |
| Normalized Unique     | NFKC、trim、合併連續空白後的 distinct count       |
| Unique Source         | `exact` 或 `approximate`                 |
| Unique %              | normalized unique 除以非 strict-null 筆數    |
| Normalization Changed | 正規化後字串發生變化的筆數                           |
| Candidate Type        | profiler 推測的資料型別                        |
| Type Match %          | 符合候選型別的比例                               |
| Type Failures         | 無法解析成候選型別的筆數                            |
| P99 / Max Length      | 99 百分位及最大字串長度                           |
| Dominant Value %      | 最常見值占非空值的比例                             |
| Delimiter Candidates  | 字段出現 comma、semicolon、pipe 的頻率           |
| Pair Observations     | 與配對欄位發現的不一致                             |
| Review Flags          | 所有 heuristic warning                    |

### Priority 的意義

* `High`：可能造成錯誤拆分、位置錯配或型別轉換失敗。
* `Medium`：需要定義明確清洗規則。
* `Low`：值得確認，但通常不阻塞 ingestion。
* `None`：目前 heuristic 沒有發現明顯問題，不代表已完成語意驗證。

## 三、Null Review：決定哪些值才是真正 NULL

必須區分：

* Strict null：空字串或只有 whitespace。
* Candidate null：內容是 `NA`、`NR`、`.`、`Unknown` 等字串。

不能全域執行：

```python
value in {"NA", "NR", "Unknown"} -> None
```

必須依欄位判斷。例如這份報告中：

* `COUNTRY OF ORIGIN` 有 99.90% 是 `NR`，很可能代表 not reported。
* `REPLICATION SAMPLE SIZE` 大量使用 `NA`，通常表示沒有 replication sample。
* `REPORTED GENE(S)` 同時出現 `NR`、`NA`、`Unknown`、`-`、`N/A`，可能需要保留不同 missing reason。

建議填寫：

* `Approved As NULL`：Yes／No／Conditional
* `Missing Reason`：例如 `not_reported`、`not_applicable`、`unknown`
* `Decision` 或 `Notes`：記錄欄位級規則與例外

Candidate NULL 的決策會影響 datatype、pair presence 與資料完整性，因此應優先完成。

## 四、Datatype Review：不要只看 Match %

`Candidate Type` 是格式推測，不是最終 database type。

這份資料的典型案例：

* `CHR_ID` 推測為 integer，但有 9,361 筆失敗，包括 `X`、`15 x 6`。

  * 不適合直接存成整數。
  * 建議 raw 欄位保存 string，再建立解析後 chromosome/locus 子結構。
* `CHR_POS` 有 5,238 筆類似 `78664464 x 133674649`。

  * 不是單一 position。
  * 不應直接 cast integer。
* `SNP_ID_CURRENT` 有 suffix、decimal-like value。

  * identifier 應使用 string。
* `OR or BETA` 有 2 筆 `Infinity`。

  * 建議 decimal nullable，加 `parse_status` 或 `non_finite_flag`。
* `RISK ALLELE FREQUENCY` 超過 51% 是候選 NULL，另有區間及文字值。

  * 可保留 raw string，再產生 nullable numeric parsed value。

`Match % = 99%` 仍不代表可以安全直接 cast；剩下 1% 在百萬筆資料中可能是數千筆。

## 五、Multivalue Review：出現 delimiter 不代表可拆分

這是最容易誤判的部分。

例如：

* `INITIAL SAMPLE SIZE` 有 97.13% 包含 comma。
* 但 comma 可能是數字千分位，例如 `47,745`。
* 也可能是自然語言中的標點。
* `STUDY`、`DISEASE/TRAIT` 中的 comma 也可能只是標題內容。

因此：

```text
Rows Containing comma 很高
```

只代表字串包含 comma，不代表這是一個 comma-separated array。

需要確認：

* 是否真的是多值欄位？
* delimiter 是否有 escaping 或 quoting？
* 順序是否重要？
* duplicate token 是否可去除？
* empty token 是否表示缺少位置，還是單純標點？

在未確認前，ETL 必須保留完整 raw string，不能直接 `split(",")`。

## 六、Pair Consistency：避免錯誤 zip

這張表用來檢查名稱與 identifier 的配對，例如：

```text
MAPPED_TRAIT ↔ MAPPED_TRAIT_URI
EFO term ↔ EFO URI
```

目前重要結果：

| 配對                              | comma token mismatch |
| ------------------------------- | -------------------: |
| associations：MAPPED_TRAIT ↔ URI |                9,191 |
| studies：MAPPED_TRAIT ↔ URI      |                3,973 |
| trait mappings：EFO term ↔ URI   |                1,616 |

這不一定表示來源資料錯誤。報告中的例子顯示 trait 名稱本身可能含 comma，例如：

```text
psoriasis 14, pustular
```

若直接用 comma split，左側會被拆成兩個 token，但右側仍只有一個 URI，於是形成假 mismatch。

因此不能直接：

```python
zip(mapped_trait.split(","), mapped_trait_uri.split(","))
```

較安全的方向是：

* 先確認 GWAS Catalog 對該欄位的正式 delimiter 規則。
* 優先依 EFO URI 或 trait mapping file 建立關聯。
* 無法可靠拆分時，保存 raw pair，標記 `pair_parse_status=ambiguous`。
* 不要為了讓數量一致而丟棄或補空 token。

另外，目前 pair presence 只把空字串視為 missing；尚未套用你在 Null Review 核准的 `NA/NR` 規則。因此 NULL 規則完成後，pair validation 應再執行一次。

## 七、Review Queue：真正的工作清單

這一頁不是 reject list，而是 data contract backlog。

建議處理順序：

1. 篩選 `load_to_curated` roles。
2. 處理全部 13 個 High。
3. 接著處理：

   * `CANDIDATE_NULL_TOKEN`
   * `TYPE_PARSE_FAILURE`
   * `NORMALIZATION_IMPACT`
   * `DUPLICATE_MULTIVALUE_TOKEN`
4. 最後處理：

   * `HIGH_NULL_RATE`
   * `DOMINANT_VALUE`
   * `LENGTH_OUTLIER`
   * `POSSIBLE_MULTIVALUE`

每個項目至少填：

* `Decision`：採用的明確規則。
* `Status`：Pending → In Review → Approved／Accepted Risk。
* `Reviewer`：負責人。
* `Notes`：判斷依據、官方文件或抽樣結果。

## 最終要從報告產出什麼

完成審查後，應把人工決策轉成版本化的 dataset contract，例如：

```json
{
  "role": "published_associations",
  "column": "CHR_ID",
  "raw_type": "string",
  "curated_type": "string",
  "nullable": false,
  "split_rule": null,
  "normalization": ["unicode_nfkc", "trim", "collapse_whitespace"],
  "parse_policy": "preserve_raw_and_parse_locus_components",
  "on_parse_failure": "flag"
}
```

最重要的原則是：

* report 的 warning 不等於資料錯誤。
* candidate 不等於 approved rule。
* 高 NULL 欄位不代表應刪除。
* delimiter 出現不代表可以 split。
* parse failure 不應直接丟棄資料。
* 所有 transformation 都應保留 raw value、規則版本及 quality flag。

而且這是欄位級報告，無法取代 row-level validation。正式 ETL 還需要輸出每筆資料的 `parse_status`、`quality_flags`、`rejection_reason` 或 quarantine record。
