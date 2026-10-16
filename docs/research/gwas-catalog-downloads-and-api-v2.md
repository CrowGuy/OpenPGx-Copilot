# GWAS Catalog 下載格式、REST API v2 與 r2026-10-03 跨檔不一致研究

- 調查日期：2026-10-16
- 背景：[#31](https://github.com/CrowGuy/OpenPGx-Copilot/issues/31)，r2026-10-03 的 cross-file validation 失敗（79 個 study、5,790 列 associations 不在 studies 檔）。
- 範圍：只採用官方一手來源（ebi.ac.uk/gwas 文件、news、FTP、API v2 回應與 OpenAPI spec、EBISPOT GitHub）。每一段「觀察」都附上可重跑的 URL。
- 我們使用的端點見 `raw/gwas_catalog/contracts/gwas_dataset_contract.json` 與 [gwas-raw-snapshot-playbook](../gwas-raw-snapshot-playbook.md)。

## 摘要

- 官方下載頁目前列出的格式只有 v1.0、v1.0.2（associations）、v1.0.2.1、v1.0.3.1（studies / ancestries / unpublished）與 trait mappings；**沒有比 v1.0.3.1 更新的格式**，連結全部指向 FTP `releases/latest/`。下載頁沒有提到我們使用的 `/gwas/api/search/downloads/...` 端點。（[file-downloads](https://www.ebi.ac.uk/gwas/docs/file-downloads)）
- 我們使用的 6 個 `/gwas/api/search/downloads/...` 端點今天都回 200，回傳的檔案與 FTP `releases/latest/` 對應檔案**大小完全相同**（未比 checksum）；換成 FTP 應該不會改變資料內容，r2026-10-03 的不一致在 FTP 版本同樣存在。（見 [問題 1 的觀察](#觀察我們的端點與-ftp-是同一份檔案)）
- 官方在 2025-11-10 說明：程式化下載應改用 public FTP，舊端點 `ebi.ac.uk/gwas/api/search/downloads/full`「has been deprecated」。我們用的 versioned 端點沒有被點名，也**沒有公告任何淘汰時程**。（[association-file-update](https://www.ebi.ac.uk/gwas/docs/news/association-file-update)）
- REST API v1 已退役：文件寫「V1 was retired in August 2026」，舊路徑現在回 HTTP 410。v2 是唯一支援的版本；[`/v2/metadata`](https://www.ebi.ac.uk/gwas/rest/api/v2/metadata) 的 `data_release_date`（今天是 `2026-10-03`）可以程式化取得目前 release。（[REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)）
- 官方明確表示 v2 **不是**用來取代 bulk download：「For bulk access, download the GWAS Catalog flat files instead of crawling the API.」限速為每 IP 100 requests/min 與 15 requests/s，超過回 429。（[REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)）
- 找不到任何官方對「associations 檔引用 studies 檔沒有的 study」的說明或 known issue；FAQ 反而寫每次 release 會更新「all downloadable spreadsheets」。（[FAQ](https://www.ebi.ac.uk/gwas/docs/faq#faqA7UpdateFrequency)）
- 抽查 12 個缺漏 accession：12 個都能在 API v2 `/v2/studies/{id}` 取得；其中 **7 個仍出現在 r2026-10-03 的 unpublished_studies 檔**，狀態欄位是 `not yet curated`，這與 #31 記錄的「出現在 unpublished_studies：0」不一致，需要重新確認。
- r2026-10-03 studies 檔的 `DATE ADDED TO CATALOG` 最大值是 **2026-09-10**，而缺漏的 associations 列是 2026-09-15 ～ 2026-09-27：studies 檔的內容停在較早的日期，associations 檔較新。官方沒有說明原因。

## 1. Bulk download 目前的格式與檔案

### 官方列出的檔案（sourced）

[Downloading the GWAS Catalog](https://www.ebi.ac.uk/gwas/docs/file-downloads) 頁面寫「Data is released biweekly. The download links in the table below point to the latest directory.」，並列出：

| 資料 | 格式版本 | FTP 檔名（`releases/latest/`） |
|---|---|---|
| All associations | v1.0 | `gwas-catalog-associations-full.zip`、`gwas-catalog-associations-split.zip` |
| All associations（ontology annotated、study accession、genotyping technology） | v1.0.2 | `gwas-catalog-associations_ontology-annotated-full.zip`、`gwas-catalog-associations_ontology-annotated-split.zip` |
| All studies | v1.0 | `gwas-catalog-studies.tsv` |
| All studies | v1.0.2.1 | `gwas-catalog-studies-download-alternative-v1.0.2.1.txt` |
| All studies（「with added fields to match the unpublished downloads」） | v1.0.3.1 | `gwas-catalog-download-studies-v1.0.3.1.txt` |
| All ancestry data | v1.0 | `gwas-catalog-ancestry.tsv` |
| All ancestry data | v1.0.3.1 | `gwas-catalog-download-ancestries-v1.0.3.1.txt` |
| Unpublished studies | v1.0.3.1 | `gwas-catalog-unpublished-studies-v1.0.3.1.tsv` |
| Unpublished ancestries | v1.0.3.1 | `gwas-catalog-unpublished-ancestries-v1.0.3.1.tsv` |
| Reported trait → EFO mappings | 無版本 | `gwas-efo-trait-mappings.tsv` |

同一頁的「File name conventions」：

- v1.0.1：「dismissed from 1 May 2018」
- v1.0.3：「dismissed from 1 Dec 2023」
- v1.0.3.1：「the addition of all fields in v1.0.3, plus cohort identifiers and summary statistics availability in the studies download」
- `eXX` 是 Ensembl release；`rYYYY-MM-DD` 是「the date on which the GWAS Catalog was released」。
- 「Older versions of the GWAS Catalog ... can be found on our FTP server」，即 [releases 封存目錄](https://ftp.ebi.ac.uk/pub/databases/gwas/releases)。
- 「Checking the current release programmatically」建議使用 [`/gwas/rest/api/v2/metadata`](https://www.ebi.ac.uk/gwas/rest/api/v2/metadata)。

[2025-11-10 的 news](https://www.ebi.ac.uk/gwas/docs/news/association-file-update) 說明 associations 檔超過 100 萬列後改為 zip，並提供 split 版本（「divided by publication year, with a separate file for each year from 2023 onwards, and pre-2023 data in a single file」），並寫「data format unchanged」。

**沒有找到新的資料模型或新的下載格式公告。** News 列表（[news](https://www.ebi.ac.uk/gwas/docs/news)）2025–2026 只有 API v2 發布、API v2 migration guide、associations 檔改 zip、徵求提交四篇。

### 觀察：FTP 目錄結構（2026-10-16）

- [`releases/`](https://ftp.ebi.ac.uk/pub/databases/gwas/releases/) 依 `YYYY/MM/DD/` 存放每次 release，另有 `latest/`。
- 2026 年的目錄：`2026/08/03`、`2026/08/24`、`2026/09/04`、`2026/09/15`、`2026/10/05`。
- **r2026-10-03 這一版在 FTP 的目錄是 [`2026/10/05/`](https://ftp.ebi.ac.uk/pub/databases/gwas/releases/2026/10/05/)**，檔案時間 2026-10-05 11:50；FTP 目錄日期與檔名中的 release date 不同。（觀察，未見官方說明兩者關係）
- `latest/` 與 `2026/10/05/` 內 12 個檔案相同，FTP 上的檔名**不含** release date 與 Ensembl 版本。

### 觀察：我們的端點與 FTP 是同一份檔案

2026-10-16 對我們使用的端點送 HEAD request，再比對 FTP `latest/` 的 `Content-Length`：

| 我們的端點 | `Content-Disposition` filename | 大小 (bytes) | 對應 FTP 檔案 | FTP 大小 |
|---|---|---|---|---|
| [`associations/v1.0.2?split=false`](https://www.ebi.ac.uk/gwas/api/search/downloads/associations/v1.0.2?split=false) | `gwas_catalog_v1.0.2-associations_e116_r2026-10-03_full.zip` | 72,826,184 | `gwas-catalog-associations_ontology-annotated-full.zip` | 72,826,184 |
| [`studies/v1.0.3.1`](https://www.ebi.ac.uk/gwas/api/search/downloads/studies/v1.0.3.1) | `gwas-catalog-v1.0.3.1-studies-r2026-10-03.tsv` | 129,219,103 | `gwas-catalog-download-studies-v1.0.3.1.txt` | 129,219,103 |
| [`ancestries/v1.0.3.1`](https://www.ebi.ac.uk/gwas/api/search/downloads/ancestries/v1.0.3.1) | `gwas-catalog-v1.0.3.1-ancestries-r2026-10-03.tsv` | 53,445,127 | `gwas-catalog-download-ancestries-v1.0.3.1.txt` | 53,445,127 |
| [`unpublished_studies/v1.0.3.1`](https://www.ebi.ac.uk/gwas/api/search/downloads/unpublished_studies/v1.0.3.1) | `gwas-catalog-v1.0.3.1-unpublished-studies-r2026-10-03.tsv` | 7,974,005 | `gwas-catalog-unpublished-studies-v1.0.3.1.tsv` | 7,974,005 |
| [`unpublished_ancestries/v1.0.3.1`](https://www.ebi.ac.uk/gwas/api/search/downloads/unpublished_ancestries/v1.0.3.1) | `gwas-catalog-v1.0.3.1-unpublished-ancestries-r2026-10-03.tsv` | 7,075,241 | `gwas-catalog-unpublished-ancestries-v1.0.3.1.tsv` | 7,075,241 |
| [`trait_mappings`](https://www.ebi.ac.uk/gwas/api/search/downloads/trait_mappings) | `gwas_catalog_trait-mappings_r2026-10-03.tsv` | 19,481,277 | `gwas-efo-trait-mappings.tsv` | 19,481,277 |

- 大小完全一致；沒有逐檔計算 checksum，所以「內容相同」是依大小推定。
- 端點回應沒有 `Deprecation`、`Sunset`、`Warning` header。
- 端點的優點是檔名帶 `r<release_date>` 與 `e<ensembl>`；FTP 檔名沒有，要從目錄或 `/v2/metadata` 取得 release date。
- 對照：`/gwas/api/search/downloads/full` 與 `/gwas/api/search/downloads/studies/v1.0.3` 目前回 404。
- [REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)在「Ontology trait mappings」仍直接連到 `https://www.ebi.ac.uk/gwas/api/search/downloads/trait_mappings`，表示這個端點目前仍被官方文件引用。

## 2. REST API v2

### 狀態與 v1 退役（sourced）

- [2025-08-11 公告](https://www.ebi.ac.uk/gwas/docs/news/rest-api-v2-release)：「The previous API version will be available alongside v2 until May 2026, so you’ll need to switch over your pipelines before then.」
- [REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)：「REST API v2 is the only currently supported version of the GWAS Catalog API. V1 was retired in August 2026.」公告預計 May 2026，實際文件寫 August 2026；兩者都照原文引用，沒有找到更精確的日期。
- [2026-08-19 migration guide](https://www.ebi.ac.uk/gwas/docs/news/rest-api-v2-migration-guide)：「Starting something new? Use v2.」
- 觀察：`https://www.ebi.ac.uk/gwas/rest/api/studies/GCST90995073` 與 `https://www.ebi.ac.uk/gwas/rest/api` 回 `HTTP/2 410`，內容是「This legacy GWAS Catalog REST API is no longer available.」並指向 migration guide。
- 同一份文件也寫 summary statistics API「was frozen in 2021 and retired in 2026」，目前沒有 summary statistics API。

### 對 release-based ingestion 有用的部分

- **Release metadata**：[`/v2/metadata`](https://www.ebi.ac.uk/gwas/rest/api/v2/metadata) 今天回傳 `data_release_date: "2026-10-03"`、`ensembl_version: "116"`、`efo_version: "v3.94.0"`、`dbsnp_build: "156"`、`gene_build: "GRCh38.p14"`、`api_release_date: "2025-08-01"`。下載頁說它「returns current release information and record counts」，但今天的回應**沒有 record counts 欄位**，OpenAPI 的 `ApiMetadataConfig` schema 也沒有。
- **Endpoints**（[OpenAPI spec](https://www.ebi.ac.uk/gwas/rest/api/v2/reference/api-docs)，由 [`swagger-config`](https://www.ebi.ac.uk/gwas/rest/api/v2/reference/api-docs/swagger-config) 指向）：`/v2/studies`、`/v2/associations`、`/v2/publications`、`/v2/single-nucleotide-polymorphisms`、`/v2/efo-traits`、`/v2/genes`、`/v2/unpublished-studies`、`/v2/body-of-works`、`/v2/studies/{accession_id}/ancestries`、`/v2/metadata` 等。
- `/v2/studies` 的 filter：`pubmed_id`、`disease_trait`、`full_pvalue_set`、`efo_id`、`efo_trait`、`accession_id`、`cohort`、`gxe`、`ancestral_group`、`no_of_individuals`、`mapped_gene` 等。**沒有依 release、date added 或 last updated 篩選的參數**，無法用 API 做增量同步。
- `StudyDto` 沒有 `date added to catalog`、curation status 或 release 欄位。`AssociationDTO` schema 有 `last_mapping_date` 與 `last_update_date`，但 `GCST90995073` 的 association 回應裡沒有這兩個欄位（觀察）。
- **分頁**：預設每頁 20 筆，需跟著 `next` link 取下一頁（[REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/#pagination)）。OpenAPI 的 `size` 只有 `minimum: 1`、`default: 20`，**沒有寫上限**。Migration guide 說 v1「up to 500 records in a single request」，v2 的上限沒有寫。
- **限速**：「The API allows up to 100 requests per minute and 15 requests per second per IP address. Requests above either limit are blocked and receive an HTTP 429 Too Many Requests response.」（[REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/#rate-limits)）。Migration guide 的寫法是超過 15 queries/s 時「subsequent calls are slowed」，兩份文件寫法不同；以 REST API 文件為準較保守。

### v2 是否要取代 bulk download（sourced）

不是。

- [REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)：「For bulk access, download the GWAS Catalog flat files instead of crawling the API. Flat files provide a more efficient and faster way to retrieve the full dataset.」
- [llms.txt](https://www.ebi.ac.uk/gwas/docs/llms.txt)：「For bulk access and large-scale analyses, download the GWAS Catalog flat files. Do not retrieve bulk datasets through repeated REST API or MCP queries.」
- 估算（推論）：以每分鐘 100 requests、每頁 20 筆計算，`/v2/associations` 今天 `totalElements` = 1,203,840，約 60,192 頁、超過 10 小時，與官方建議不符。

## 3. 我們使用的端點與格式：淘汰時程

| 我們使用的 | 官方是否有淘汰公告 | 原文 |
|---|---|---|
| `/gwas/api/search/downloads/associations/v1.0.2?split=false` | **沒有公布時程**。同一路徑家族的 `/gwas/api/search/downloads/full` 已 deprecated。 | 「If you’re trying to download the file programmatically for processing, we advise you do so from our public FTP. The previously available endpoint ebi.ac.uk/gwas/api/search/downloads/full was intended for manual access and has been deprecated.」（[2025-11-10](https://www.ebi.ac.uk/gwas/docs/news/association-file-update)） |
| associations 格式 v1.0.2 | **沒有公布時程** | 下載頁仍列為現行格式（[file-downloads](https://www.ebi.ac.uk/gwas/docs/file-downloads)） |
| `/downloads/studies/v1.0.3.1`、`ancestries/v1.0.3.1`、`unpublished_studies/v1.0.3.1`、`unpublished_ancestries/v1.0.3.1` | **沒有公布時程** | 同上；只有 v1.0.1「dismissed from 1 May 2018」與 v1.0.3「dismissed from 1 Dec 2023」有日期 |
| `/downloads/trait_mappings` | **沒有公布時程** | [REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)仍連到此端點 |

- 官方對程式化下載的建議是 FTP（上面 2025-11-10 原文），所以 versioned 端點雖然沒有被點名淘汰，也不在官方推薦路徑上。
- `api/search/downloads` 回應沒有 `Deprecation` / `Sunset` header（觀察，2026-10-16）。
- GWAS announce mailing list（`gwas-announce-join@ebi.ac.uk`，見 [2025-11-10 news](https://www.ebi.ac.uk/gwas/docs/news/association-file-update)）的 [archive](https://listserver.ebi.ac.uk/pipermail/gwas-announce/) 需要 EBI VPN，無法確認 mailing list 是否有其他公告。

## 4. Studies 與 associations 檔不同步

### 官方說法（sourced）

- 沒有找到任何官方頁面、news 或 known issue 說明 associations 檔可能引用 studies 檔沒有的 study。
- [FAQ「How often is the GWAS Catalog updated?」](https://www.ebi.ac.uk/gwas/docs/faq#faqA7UpdateFrequency)：「The GWAS Catalog adds new curated data approximately every two weeks. Each data release includes updates to the website and all downloadable spreadsheets available on the file downloads page.」也就是說官方預期每次 release 所有檔案一起更新。
- [FAQ「Does the GWAS Catalog include data that is not linked to a PubMed-indexed publication?」](https://www.ebi.ac.uk/gwas/docs/faq#faqA9PrepublishedData)：pre-published data「is not manually reviewed by curators until the study is published in a journal」，「Once a study is published, it is curated, annotated, and extended with top associations before being fully incorporated into the main database.」
- EBISPOT GitHub：在 EBISPOT org 搜尋 issue 沒有找到相關討論。Release 產生程式（API v2 metadata 的 license 連到 `github.com/EBISPOT/gwas-rest-api`，以及 `EBISPOT/goci`）目前**不是公開 repo**（GitHub API 回 404），無法從原始碼確認檔案的產生時間與方式。
- 這種情況官方提供的管道是 helpdesk `gwas-info@ebi.ac.uk`（[REST API 文件](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)、[FAQ](https://www.ebi.ac.uk/gwas/docs/faq#faqA7UpdateFrequency)）。

### 觀察：抽查 accession（2026-10-16）

API v2 [`/v2/studies/{accession}`](https://www.ebi.ac.uk/gwas/rest/api/v2/studies/GCST90995073)、[`/v2/unpublished-studies/{accession}`](https://www.ebi.ac.uk/gwas/rest/api/v2/unpublished-studies/GCST90726393)、[`/v2/publications/{pubmed_id}`](https://www.ebi.ac.uk/gwas/rest/api/v2/publications/41937692)，以及 r2026-10-03 的 [unpublished_studies 檔](https://www.ebi.ac.uk/gwas/api/search/downloads/unpublished_studies/v1.0.3.1)（7.9 MB，完整下載後 grep）：

| Accession | `/v2/studies` | PubMed | publication_date | `/v2/unpublished-studies` (`date_submitted`) | r2026-10-03 unpublished_studies 檔 |
|---|---|---|---|---|---|
| GCST90652490 | 200（Orofacial clefts） | 27033726 | 2016-03-30 | 404 | 無 |
| GCST90726393 | 200（Bladder cancer） | 42706231 | 2026-08-08 | 200（2025-09-15） | **有**，`not yet curated` |
| GCST90726394 | 200 | 42706231 | 2026-08-08 | 200（2025-09-15） | **有**，`not yet curated` |
| GCST90726395 | 200 | 42706231 | 2026-08-08 | 200（2025-09-15） | **有**，`not yet curated` |
| GCST90726610 | 200（Lung adenocarcinoma） | 41581221 | 2026-06-01 | 200（2025-12-22） | **有**，`not yet curated` |
| GCST90832978 | 200（Sarcopenia index） | 42702734 | 2026-08-25 | 200（2026-04-08） | **有**，`not yet curated` |
| GCST90832979 | 200 | 42702734 | 2026-08-25 | 200（2026-04-08） | **有**，`not yet curated` |
| GCST90832980 | 200 | 42702734 | 2026-08-25 | 200（2026-04-08） | **有**，`not yet curated` |
| GCST90995073 | 200（HLA-DP B cell surface expression levels） | 41937692 | 2026-04-01 | 404 | 無 |
| GCST90995075 | 200（HLA-DR B cell surface expression levels） | 41937692 | 2026-04-01 | 404 | 無 |
| GCST90995076 | 200（Prostate cancer） | 42415294 | 2026-07-01 | 404 | 無 |
| GCST90995077 | 200（Thyroid cancer） | 42431967 | 2026-07-10 | 404 | 無 |

- 在 unpublished_studies 檔中出現的 7 列，`DATE ADDED TO CATALOG`、`PUBMED ID`、`ASSOCIATION COUNT` 欄位都是 `not yet curated`，`SUBMISSION DATE` 與 API 的 `date_submitted` 一致。
- **這與 #31 記錄的「出現在 unpublished_studies：0」不一致。** 我下載的檔案 `Content-Disposition` 是 `gwas-catalog-v1.0.3.1-unpublished-studies-r2026-10-03.tsv`、7,974,005 bytes，與 #31 是同一個 release。`tools/gwas_raw_snapshot.py` 的 cross-file check 不會讀 unpublished 檔，所以 #31 的 0 是另外手動檢查的結果，比對方式需要重新確認。
- 在 API v2 中，`StudyDto` 沒有 status 或 date-added 欄位，所以無法從 API 判斷這些 study 是在哪一次 release 加入的。
- `/v2/studies?pubmed_id=41937692` 回傳 3 個 study：`GCST90995073`、`GCST90995074`、`GCST90995075`。`GCST90995074` 不在 #31 的範例中，可能有 association 或沒有，未確認。
- `/v2/studies/GCST90995073/ancestries` 有一筆 initial ancestry（148 European，U.S.），`/v2/associations?accession_id=GCST90995073` 有 1 筆 association（association_id 227602946）。
- API v2 今天的 `totalElements`：`/v2/studies` 232,202、`/v2/associations` 1,203,840、`/v2/unpublished-studies` 29,153。#31 的 associations 檔是 1,198,394 列。API 與檔案的計數單位不一定相同（例如一列對多個 SNP），**不能用來判斷 API 是否比檔案新**。
- **studies 檔的 `DATE ADDED TO CATALOG` 最大值是 2026-09-10。** 2026-10-16 從 [`studies/v1.0.3.1` 端點](https://www.ebi.ac.uk/gwas/api/search/downloads/studies/v1.0.3.1)（`r2026-10-03`）串流整個檔案（未存檔），用 awk 統計：230,057 筆資料列；2026-09 之後的 `DATE ADDED TO CATALOG` 只有 2026-09-01（4）、2026-09-08（7,563）、2026-09-09（7）、2026-09-10（66），**沒有任何 2026-09-10 之後的日期**；上表 13 個 accession 都不在檔案中。#31 缺漏的 associations 列是 2026-09-15 ～ 2026-09-27。
- 同一時間 API v2 `/v2/studies` 的 `totalElements` 是 232,202，比 studies 檔多 2,145。

## 對我們的影響（推論）

以下是推論，不是官方說法。

- **換成 FTP 解決不了 #31。** 端點與 FTP 是同一份檔案，r2026-10-03 的 studies 檔在兩邊都缺這些 study。
- **最可能的原因是 r2026-10-03 的 studies / unpublished 檔是從較舊的資料匯出，associations 檔較新。** 證據：studies 檔最大 `DATE ADDED TO CATALOG` 是 2026-09-10，缺漏的 associations 是 2026-09-15..27；7 個先前以 unpublished 提交的 study 在 unpublished 檔仍標 `not yet curated`。官方沒有說明，不能當作已確認的原因；這也表示下一版很可能自然補齊，但不保證。
- **端點淘汰的風險是「沒有時程但不在推薦路徑」。** 官方推薦程式化下載用 FTP；versioned 端點目前正常，也被 REST API 文件引用。如果將來要遷移，FTP 檔名沒有 release date 與 Ensembl 版本，需要改用 `releases/YYYY/MM/DD/` 目錄加 `/v2/metadata` 判斷 release，`filename_pattern` 與 discovery 邏輯都要改。這次不需要做。
- **API v2 不適合當 bulk 來源，但適合做個別 study 的佐證。** 例如在 cross-file 失敗時，用 `/v2/studies/{id}` 與 `/v2/unpublished-studies/{id}` 確認缺漏 study 的狀態，並注意 100 requests/min 限制。
- **`/v2/metadata` 的 `data_release_date` 可以作為 discovery 的交叉檢查**，與端點檔名的 release date 比對。
- **建議寫信給 `gwas-info@ebi.ac.uk` 回報。** 這是官方唯一的回報管道；附上 79 個 accession 與 release date。
- #31 的「下一版同樣失敗」討論可以參考：失敗的 study 是否都在 unpublished 檔中以 `not yet curated` 出現，可以讓 CurationContract 把這類 study 和真正來源不明的 study 分開計算（會修改 ADR-0007，需另外討論）。

## 未能確認的事項

- 79 個缺漏 study 的完整名單：本次只抽查 #31 列出的 12 個（另加 GCST90995074）。研究完成後已在伺服器上比對全部 79 個：7 個 study（1,922 列）在 unpublished_studies 檔，其餘 72 個 study（3,868 列）兩個檔都沒有（[#31 更正留言](https://github.com/CrowGuy/OpenPGx-Copilot/issues/31#issuecomment-6211305875)）。
- v1 REST API 退役的確切日期：公告寫「until May 2026」，文件寫「retired in August 2026」，沒有更精確的日期。
- 官方 release 產生流程（各檔是否同時從同一個 database snapshot 匯出）：相關 repo 不公開，文件沒有說明。
- FTP 目錄日期（`2026/10/05`）與檔名 release date（`r2026-10-03`）的關係：沒有官方說明。
- `/v2/metadata` 文件說會回傳 record counts，實際回應沒有。
- API v2 `size` 參數的上限：OpenAPI 與文件都沒有寫。
- GWAS announce mailing list 是否有其他公告：archive 需要 EBI VPN。
- 端點與 FTP 檔案內容相同：只比對了大小，沒有計算 checksum。
- 過去的 release 是否也有相同的跨檔不一致：未檢查。

## 來源

官方文件與公告：

- [Downloading the GWAS Catalog（file-downloads）](https://www.ebi.ac.uk/gwas/docs/file-downloads)
- [REST API（programmatic access）](https://www.ebi.ac.uk/gwas/docs/programmatic-access/rest-api/)
- [Frequently Asked Questions](https://www.ebi.ac.uk/gwas/docs/faq)
- [News 列表](https://www.ebi.ac.uk/gwas/docs/news)
- [The GWAS Catalog REST API Version 2.0 is here!（2025-08-11）](https://www.ebi.ac.uk/gwas/docs/news/rest-api-v2-release)
- [Changes to associations tsv download file（2025-11-10）](https://www.ebi.ac.uk/gwas/docs/news/association-file-update)
- [Version 2 of the GWAS Catalog REST API: what’s changed from v1?（2026-08-19）](https://www.ebi.ac.uk/gwas/docs/news/rest-api-v2-migration-guide)
- [GWAS Catalog Documentation llms.txt](https://www.ebi.ac.uk/gwas/docs/llms.txt)

API v2 與 OpenAPI：

- [`/v2/metadata`](https://www.ebi.ac.uk/gwas/rest/api/v2/metadata)
- [OpenAPI spec](https://www.ebi.ac.uk/gwas/rest/api/v2/reference/api-docs)、[swagger-config](https://www.ebi.ac.uk/gwas/rest/api/v2/reference/api-docs/swagger-config)、[API docs](https://www.ebi.ac.uk/gwas/rest/api/v2/docs)
- [`/v2/studies/GCST90995073`](https://www.ebi.ac.uk/gwas/rest/api/v2/studies/GCST90995073)、[`/v2/unpublished-studies/GCST90726393`](https://www.ebi.ac.uk/gwas/rest/api/v2/unpublished-studies/GCST90726393)、[`/v2/publications/41937692`](https://www.ebi.ac.uk/gwas/rest/api/v2/publications/41937692)、[`/v2/associations?accession_id=GCST90995073`](https://www.ebi.ac.uk/gwas/rest/api/v2/associations?accession_id=GCST90995073)
- [舊 API（410）](https://www.ebi.ac.uk/gwas/rest/api/studies/GCST90995073)

下載與 FTP：

- [FTP releases](https://ftp.ebi.ac.uk/pub/databases/gwas/releases/)、[`latest/`](https://ftp.ebi.ac.uk/pub/databases/gwas/releases/latest/)、[`2026/10/05/`](https://ftp.ebi.ac.uk/pub/databases/gwas/releases/2026/10/05/)
- 我們使用的端點：見 `raw/gwas_catalog/contracts/gwas_dataset_contract.json`

GitHub：

- [EBISPOT org](https://github.com/EBISPOT)（issue 搜尋無相關結果；`gwas-rest-api`、`goci` 不公開）
