# OpenPGx

以公開資料為基礎的基因解讀專案。近期只建置 GWAS Data Platform，Copilot 是之後才決定是否建置的上層應用。

## Language

### 專案分層

**GWAS Data Platform**:
團隊共用、可查詢的 GWAS Catalog 資料庫，以及產生它的 ETL 流程；是目前唯一在建置的層。
_Avoid_: 資料庫專案、ETL 專案

**Copilot**:
未來建立在 GWAS Data Platform 之上的 web／mobile 解讀應用；只能讀 Rule Evidence，不能直接讀 Curated Layer。目前不在 scope 內。
_Avoid_: App、前端、chatbot

**Rule Evidence**:
從某個 Release 的 Curated Layer 整理、審查後，供 Copilot 使用的證據；是 Copilot 唯一能讀的資料。尚未建置。
_Avoid_: evidence（單獨使用）、curated data

### 來源取得

**Source Release**:
GWAS Catalog 官方發布的一個資料版本，以 release date 識別（例如 `2026-08-22`）。
_Avoid_: 官方版本、upstream version

**Discovery**:
探測 EBI endpoint，判斷是否有新 Source Release 並給出 `candidate_ready`、`no_new_release` 或 `review_required` 結論的步驟。
_Avoid_: 檢查更新、polling

**Review Required**:
Discovery 或驗證遇到無法自動判斷的情況時的狀態，必須由人依 playbook 處理才能繼續。
_Avoid_: warning、待確認

**RawSnapshot**:
某個 Source Release 的原始檔案，下載後附 manifest 與 sha256、不可再修改；是所有下游資料的唯一源頭。
_Avoid_: dump、快照版本、raw data

**DatasetContract**:
經審查的來源取得規格：允許的 endpoint、檔名格式、header、欄位數與每個檔案的 Load Policy。
_Avoid_: schema、資料契約（單獨使用時有歧義）

**Load Policy**:
DatasetContract 中對每個來源檔案的處置：`load_to_curated` 進入 Curated Layer，`raw_only` 只保留在 RawSnapshot。
_Avoid_: 匯入設定

**Profile**:
對 RawSnapshot 做的唯讀欄位與欄位配對統計，用來支援人工審查。
_Avoid_: 資料分析、EDA

### GWAS 內容

**Association**:
GWAS Catalog 中一筆已發表的 variant（或 variant 組合）與 trait 之間的統計關聯；來源沒有 ID，由 Curated Layer 給代理鍵。
_Avoid_: hit、signal、finding

**Variant Token**:
Association 的 SNPS 欄位拆分後的單一識別碼，可能是 rsID、`chr:pos` 座標或其他名稱（例如 HLA allele）。
_Avoid_: SNP（泛指時有歧義）、rs number

**SNP Combination**:
一筆 Association 中 Variant Token 之間的關係：`single`、`haplotype`、`interaction`、`list` 或 `alternative`。
_Avoid_: multi-SNP、SNP set

**Risk Allele**:
Variant Token 上被報告與 trait 關聯的 allele；`?` 表示來源未標明，不能用來判斷效應方向。
_Avoid_: effect allele、alt allele

**Locus Alignment**:
Variant Token 與其染色體位置、risk allele 是否能依位置一一對應；對不上時不配對，標記為 misaligned。
_Avoid_: zip、pairing

### Curated 與發布

**CurationContract**:
由 Profile 審查結果轉成的版本化欄位層級規則：型別、空值、多值拆分方式，以及 Rejection Threshold。
_Avoid_: DatasetContract、column spec

**Curated Layer**:
依 CurationContract 把 `load_to_curated` 檔案正規化後、可直接查詢的表。
_Avoid_: clean data、warehouse

**Release**:
一個 RawSnapshot 依某版 CurationContract 載入後的完整 Curated Layer，以 `r<release date>` 識別，內容不可變。
_Avoid_: version、batch、load

**Release Status**:
Release 的生命週期：`loading` → `candidate` → `active` → `retired`。
_Avoid_: stage、phase

**Candidate**:
已完成載入、等待人工審查的 Release；不能被 Copilot 或其他下游當作正式資料使用。
_Avoid_: draft、pending

**Active Release**:
目前經核准、團隊預設查詢會看到的唯一 Release。
_Avoid_: latest、current version、production

**Promote**:
人工核准一個 Candidate 成為 Active Release，同時把前一個 Active Release 標為 `retired` 的動作。
_Avoid_: deploy、publish、上線

**Required Field**:
CurationContract 中標記為必要的欄位；解析失敗時整列成為 Rejected Row。非 Required Field 解析失敗時只把該欄設為空值，整列保留。
_Avoid_: key field、mandatory column

**Rejected Row**:
違反 CurationContract 而沒有進入 Curated Layer 的來源列，連同違規原因一起保留。
_Avoid_: bad row、error、dropped row

**Rejection Threshold**:
CurationContract 規定的 Rejected Row 比例上限；超過時整個 Release 載入失敗。
_Avoid_: tolerance、容錯率

**Release Pin**:
下游（例如產生 Rule Evidence 的整理流程）宣告自己固定使用某個特定 Release，而不是跟隨 Active Release。
_Avoid_: lock、依賴版本
