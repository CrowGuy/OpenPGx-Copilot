# OpenPGx

以公開資料為基礎的基因解讀專案。近期只建置 GWAS Data Platform，Copilot 是之後才決定是否建置的上層應用。

## Language

### 專案分層

**GWAS Data Platform**:
團隊共用、可查詢的 GWAS Catalog 資料庫，以及產生它的 ETL 流程；是目前唯一在建置的層。
_Avoid_: 資料庫專案、ETL 專案

**Copilot**:
未來建立在 GWAS Data Platform 之上的 web／mobile 解讀應用；目前不在 scope 內。
_Avoid_: App、前端、chatbot

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

**Rejected Row**:
違反 CurationContract 而沒有進入 Curated Layer 的來源列，連同違規原因一起保留。
_Avoid_: bad row、error、dropped row

**Rejection Threshold**:
CurationContract 規定的 Rejected Row 比例上限；超過時整個 Release 載入失敗。
_Avoid_: tolerance、容錯率

**Release Pin**:
下游（例如未來的 Copilot）宣告自己固定使用某個特定 Release，而不是跟隨 Active Release。
_Avoid_: lock、依賴版本
