import re
from dataclasses import dataclass

KNOWN_SKILLS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "vue",
    "angular",
    "node.js",
    "fastapi",
    "django",
    "spring",
    "sql",
    "mysql",
    "postgresql",
    "aws",
    "azure",
    "docker",
    "kubernetes",
    "git",
    "excel",
    "power bi",
    "figma",
}

TAIWAN_CITIES = (
    "台北市",
    "臺北市",
    "新北市",
    "桃園市",
    "台中市",
    "臺中市",
    "台南市",
    "臺南市",
    "高雄市",
    "基隆市",
    "新竹市",
    "新竹縣",
    "苗栗縣",
    "彰化縣",
    "南投縣",
    "雲林縣",
    "嘉義市",
    "嘉義縣",
    "屏東縣",
    "宜蘭縣",
    "花蓮縣",
    "台東縣",
    "臺東縣",
    "澎湖縣",
    "金門縣",
    "連江縣",
)


@dataclass(frozen=True)
class FieldRules:
    name: tuple[str, ...]
    title: tuple[str, ...]
    years: tuple[str, ...]
    skills: tuple[str, ...]
    city: tuple[str, ...] = ("居住地", "居住地區", "所在地", "通訊地址")


def label(text: str, labels: tuple[str, ...], max_length: int = 100) -> str | None:
    """Read either a same-line value or the first non-heading line below a label."""
    joined = "|".join(re.escape(item) for item in sorted(labels, key=len, reverse=True))
    same_line = re.search(
        rf"(?:^|\n)\s*(?:{joined})\s*[：:]\s*([^\n\r|]{{1,{max_length}}})",
        text,
        re.I,
    )
    if same_line:
        return same_line.group(1).strip(" \t：:")
    next_line = re.search(
        rf"(?:^|\n)\s*(?:{joined})\s*[：:]?\s*\n\s*([^\n\r|]{{1,{max_length}}})",
        text,
        re.I,
    )
    return next_line.group(1).strip(" \t：:") if next_line else None


def _name(text: str, aliases: tuple[str, ...]) -> tuple[str | None, float]:
    value = label(text, aliases, 40)
    if value:
        return value, 0.98
    excluded = {"履歷", "自傳", "工作經歷", "技能專長", "學歷", "基本資料"}
    for line in (item.strip() for item in text.splitlines()[:12]):
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", line) and line not in excluded:
            return line, 0.62
    return None, 0.0


def _skills(text: str, aliases: tuple[str, ...]) -> list[str]:
    lower = text.lower()
    result = sorted(
        skill for skill in KNOWN_SKILLS if re.search(rf"(?<!\w){re.escape(skill)}(?!\w)", lower)
    )
    skill_line = label(text, aliases, 400)
    if skill_line:
        existing = {skill.lower() for skill in result}
        # Whitespace is intentionally not a delimiter: many canonical skills
        # (Power BI, Node.js tooling names) contain spaces.
        for item in re.split(r"[,，、;/|]+", skill_line):
            item = item.strip().strip("。")
            if 1 < len(item) <= 100 and item.lower() not in existing:
                result.append(item)
                existing.add(item.lower())
    return result


def extract_fields(text: str, rules: FieldRules) -> tuple[dict, dict[str, float]]:
    name, name_score = _name(text, rules.name)
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
    phone_match = re.search(
        r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)", text
    )
    city_value = label(text, rules.city, 100)
    city_source = city_value or text
    city = next(
        (item.replace("臺", "台") for item in TAIWAN_CITIES if item in city_source), None
    )
    title = label(text, rules.title)
    years_labels = "|".join(re.escape(item) for item in rules.years)
    years_match = re.search(
        rf"(?:{years_labels})\s*[：:]?\s*(\d+(?:\.\d+)?)\s*年", text, re.I
    )
    years = float(years_match.group(1)) if years_match else None
    skills = _skills(text, rules.skills)
    payload = {
        "name": name,
        "email": email_match.group(0).lower() if email_match else None,
        "phone": phone_match.group(0) if phone_match else None,
        "city": city,
        "current_title": title,
        "total_years": years,
        "skills": skills,
    }
    confidence = {
        "name": name_score,
        "email": 0.99 if email_match else 0.0,
        "phone": 0.97 if phone_match else 0.0,
        "city": 0.9 if city else 0.0,
        "current_title": 0.88 if title else 0.0,
        "total_years": 0.92 if years_match else 0.0,
        "skills": min(0.95, 0.55 + len(skills) * 0.05) if skills else 0.0,
    }
    return payload, confidence
