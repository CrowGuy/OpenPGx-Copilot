# Curated Layer 使用自架 PostgreSQL，只開放內網

Curated Layer 要讓開發團隊多人同時查詢，未來 Copilot 需要的表也要在同一處管理，因此選擇 PostgreSQL，以 Docker 跑在團隊伺服器上，只開放內網連線，並啟用 TLS 與 `scram-sha-256` 驗證。

## Considered Options

- **SQLite**：零依賴，但不適合多人連線與權限控管。
- **DuckDB**：分析效能最好，但屬於單檔嵌入式，不適合作為共用服務。
- **雲端託管 PostgreSQL**：維運成本最低，但團隊選擇自架。

## Consequences

- 備份、升級、帳號管理由團隊自行負責（見 ADR-0008）。
- 本機的 Profile 工具繼續使用 sqlite3，不受影響。
