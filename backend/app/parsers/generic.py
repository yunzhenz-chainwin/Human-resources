from app.parsers.common import FieldRules

PLATFORM = "generic"
VERSION = "generic-2026.07-v1"
RULES = FieldRules(
    name=("姓名", "中文姓名", "Name"),
    title=("目前職稱", "現職", "職稱", "職務類別", "Title"),
    years=("工作年資", "總年資", "工作經驗", "年資"),
    skills=("技能與專長", "專長", "技能", "Skills"),
)
