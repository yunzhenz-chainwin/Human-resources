from app.parsers.common import FieldRules

PLATFORM = "p1111"
VERSION = "p1111-2026.07-v1"
SIGNATURES = ("1111人力銀行", "1111.com.tw", "1111 履歷", "1111履歷表")
RULES = FieldRules(
    name=("姓名", "中文姓名", "履歷姓名"),
    title=("目前職稱", "現職", "職稱"),
    years=("工作年資", "總年資", "累計年資", "工作經驗"),
    skills=("專長", "技能", "專長技能", "電腦技能", "擅長工具"),
)
