# 採用輕量治理，不實作 certified compiler

舊設計（`docs/00–10`，已自 working tree 刪除、保留於 git history）規劃了 certified compiler、exception review、release approval 等完整治理，目的是讓大量自動產生的 rule 不必逐條審查。目前專案沒有 rule，定位是學習與研究原型，所以改為輕量治理：依 playbook 做人工審查、遇到無法判斷的情況進入 Review Required、每個 RawSnapshot 附 manifest、只有人能 Promote。

## Consequences

- 「candidate ≠ active」原則保留，套用在 Release 上。
- 未來若 Copilot 開始自動產生大量 rule，再重新評估 compiler 治理。
