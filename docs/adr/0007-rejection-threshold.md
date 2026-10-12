# 違反 CurationContract 的列採隔離加門檻

載入時違反 CurationContract 的列存成 Rejected Row，附上違規原因，其餘照常載入；Rejected Row 比例超過 CurationContract 定義的 Rejection Threshold 時，整個 Release 載入失敗。GWAS Catalog 必然有少量髒資料，任何違規就失敗會一直卡住流程；只隔離不設上限，則可能悄悄吞掉一次來源格式改版造成的大量錯誤。
