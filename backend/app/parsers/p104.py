from app.parsers.common import FieldRules

PLATFORM = "p104"
VERSION = "p104-2026.07-v1"
SIGNATURES = ("104人力銀行", "104.com.tw", "104 履歷", "104求職者履歷")
RULES = FieldRules(
    name=("姓名", "中文姓名", "求職者姓名"),
    title=("目前職稱", "最近工作", "現職"),
    years=("工作年資", "總年資", "累積年資", "工作經驗"),
    skills=("專長", "技能", "擅長工具", "工作技能", "電腦專長"),
)
