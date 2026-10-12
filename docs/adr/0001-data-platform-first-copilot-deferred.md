# 先建 GWAS Data Platform，Copilot 延後

專案拆成兩層：GWAS Data Platform（資料層）與 Copilot（應用層）。近期只建置資料層，Copilot 是否建置、何時建置之後再決定。理由是：已完成的 RawSnapshot、DatasetContract 與審查流程本身就構成可用的資料層，對團隊研究與學習已有價值；而 Copilot 需要的 evidence／rule 形狀，在資料層穩定前定義都太早。

## Consequences

- 資料來源近期只有 GWAS Catalog；dbSNP、PharmGKB、CPIC 等等到有具體需求再加。
- 原 `docs/00–10` 規劃的 rule engine、LLM 解釋層、OutputSafetyValidator、PGx roadmap 都不在目前 scope；需要時從 git history 取回。
