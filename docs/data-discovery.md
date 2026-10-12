# Gwas Catalog Data Discovery

## Data Discovery Phases

| 階段     | 我會協助產出的內容                                                  |
| ------ | ---------------------------------------------------------- |
| 來源盤點   | 各 TSV 版本、用途、涵蓋範圍及彼此差異                                      |
| 欄位剖析   | datatype、null rate、unique count、範例值、多值欄位格式                 |
| 資料粒度   | 每一列究竟代表 publication、study、association 還是 variant           |
| 關聯分析   | PMID、study accession、association、variant、trait 之間的 join 關係 |
| 異常分析   | 重複列、錯誤座標、缺 allele、無法 mapping、格式不一致                         |
| API 對照 | 同一批 study/association 在 API 和 TSV 的欄位及筆數差異                 |
| 版本比較   | 不同 release 的新增、修改、刪除與 identifier 穩定性                       |
| 初步模型   | raw → normalized → evidence 的 schema 草案與資料血緣               |

## 來源盤點

| TSV                                     | 資料粒度與用途                                  | 主要內容                                                                                 | 限制                                                       |
| --------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------ | -------------------------------------------------------- |
| Associations v1.0                       | 一列約代表一筆 curated association              | Variant、risk allele、p-value、OR/BETA、gene mapping、publication/study 資訊                | 缺少 ontology、study accession、genotyping technology；屬舊相容格式 |
| Associations v1.0.2 ontology-annotated  | 同上                                       | v1.0 全部欄位，加 EFO trait、EFO URI、study accession、genotyping technology                  | 仍只是 Catalog 收錄的 top associations，不是完整 summary statistics |
| Associations full                       | 所有 association 放在單一 TSV                  | 適合 ETL、自動化與 checksum                                                                 | 檔案較大                                                     |
| Associations split                      | 依 publication year 拆成多個 TSV              | 內容原則上與 full 相同，方便人工或分批處理                                                             | 增加檔案管理、去重及漏載風險                                           |
| Studies v1.0                            | 一列一個 Catalog study/analysis              | Publication、reported trait、sample description、association count                      | 缺少穩定 study accession 與較新的 metadata                       |
| Studies v1.0.2.1                        | 一列一個 study                               | 加入 accession、ontology、technology、cohort、summary-statistics availability/location、GxE | 較新的 v1.0.3.1 已提供更一致格式                                    |
| Studies v1.0.3.1                        | 一列一個 study                               | 與 unpublished study 格式對齊，保留 cohort 與 summary-statistics 資訊                           | 不包含每個 variant association 的統計結果                          |
| Ancestry v1.0                           | 一個 study 可有多列 population/stage           | Stage、樣本數、broad ancestry、來源國、招募國                                                     | 部分人口資訊仍是文字描述                                             |
| Ancestry v1.0.3.1                       | 與新版 study/unpublished 格式對齊               | 更適合統一 published/unpublished population metadata                                      | 仍需處理一對多與 ancestry label 的語意                              |
| Unpublished studies/ancestries v1.0.3.1 | 已提交但未正式出版的 GWAS                          | Accession、submission、model、sample、summary-statistics location 等                      | 多個 publication 欄位不適用；證據成熟度應與 published 分開                |
| EFO trait mappings                      | reported trait 與 ontology term 的 mapping | Reported trait、EFO/MONDO mapping、category                                            | 是多對多關係，不能假設一個 trait 只對應一個 ontology term                  |

### 它們之間的分工
可以把這組資料理解為：
- associations：發現了什麼關聯？
- studies：這個關聯來自哪個研究？
- ancestries：研究用了哪些族群與樣本？
- trait mappings：研究的 phenotype 如何標準化？
- unpublished：有哪些尚未達到 published evidence 狀態的候選研究？


### Immutable raw files 選擇

| 檔案                                          | 選擇原因                                                                                                                                                              | 若缺少的風險                                                                                           |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Associations ontology-annotated v1.0.2 full | 提供最核心的 `variant–trait association`：variant、allele、p-value、OR/BETA、mapped gene、study accession，以及 EFO ontology。選 `full` 可降低 split 檔漏載、重複載入及跨年份合併的複雜度。              | 無法建立 association-level evidence；只用 v1.0 又會缺少穩定 study accession、ontology 與 genotyping technology。 |
| Studies v1.0.3.1                            | 提供 association 所屬 study 的完整背景，例如 publication、reported trait、sample description、cohort、GxE、是否有完整 summary statistics。Study accession 可作為 associations 的主要 join key。 | Association TSV 雖重複帶有部分 study 欄位，但不足以完整描述研究設計，也容易形成大量重複資料。                                       |
| Ancestries v1.0.3.1                         | 將 study 的 population 拆成多筆結構化資料，包括 stage、樣本數、broad ancestry、招募國與來源國。這是評估研究可轉移性與族群偏差的重要資料。                                                                          | 只能依靠 studies 裡的自由文字 sample description，難以可靠地依 ancestry、stage 或 population 篩選。                    |
| EFO trait mappings                          | 建立 reported trait 與標準 ontology term 的獨立對照。它明確表達多對多 mapping，適合形成 `trait` 與 `trait_mapping` 維度表。                                                                    | 若只相信 association 內的 `MAPPED_TRAIT` 字串，容易錯誤拆分多值欄位、遺失 mapping 關係，也較難處理 ontology 更新。                |
| Unpublished studies/ancestries v1.0.3.1     | 符合「盡可能涵蓋 GWAS」的目標，可提早知道尚未出版但已提交的 study、population 與 summary-statistics location。v1.0.3.1 也與 published studies/ancestries 的 schema 較一致。                            | 完全排除會降低涵蓋率；但納入正式 evidence 又可能高估證據成熟度。                                                            |

### Raw snapshot and discover
關於如何操作 Gwas Catalog raw snapshot 和 dicover 的腳本，請參考 [gwas-raw-snapshot-playbook] (./docs/gwas-raw-snapshot-playbook.md)]。

---

## 欄位剖析

### 每個欄位要收集的資訊
| 類別          | 建議 metrics                                        | 解讀方式                                  |
| ----------- | ------------------------------------------------- | ------------------------------------- |
| 基本數量        | row count、non-null count、null count               | 確認計算母體                                |
| Null        | empty、whitespace、各種疑似 null token                  | 不要一開始就把 `NR`、`NA`、`-` 全部當 null        |
| Cardinality | raw unique、normalized unique、singleton count      | 判斷 identifier、categorical 或 free text |
| 頻率          | top values、value frequency                        | 找預設值、異常集中與拼字變體                        |
| 長度          | min/max/avg、percentiles                           | 找截斷、異常長字串                             |
| Datatype    | candidate type、parse success/failure count        | 型別推斷必須附帶 parse rate                   |
| 範例值         | common、rare、invalid、longest examples              | 讓人工可以理解欄位實際內容                         |
| 多值格式        | delimiter、token count、empty token、duplicate token | 判斷能否安全拆分                              |
| 格式規則        | regex match rate、URI/CURIE pattern                | 用於 identifier 與 ontology 欄位           |
| 關聯          | paired-field cardinality、一致性                      | 例如 trait 與 trait URI 是否一一對應           |


