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

# Common Traditional-Chinese job-title tokens. Used only to stop the last-resort
# name heuristic from emitting a leading job-title line as a personal name; they
# are never treated as names themselves.
TITLE_KEYWORDS = (
    "工程師",
    "設計師",
    "分析師",
    "建築師",
    "技師",
    "研究員",
    "經理",
    "副理",
    "協理",
    "總監",
    "主管",
    "主任",
    "課長",
    "組長",
    "專員",
    "助理",
    "顧問",
    "實習",
    "業務",
    "企劃",
    "專案",
    "研發",
    "開發",
    "執行長",
    "總經理",
)


@dataclass(frozen=True)
class FieldRules:
    name: tuple[str, ...]
    title: tuple[str, ...]
    years: tuple[str, ...]
    skills: tuple[str, ...]
    city: tuple[str, ...] = ("居住地", "居住地區", "所在地", "通訊地址")
    company: tuple[str, ...] = ("目前公司", "現職公司", "最近公司", "任職公司")
    education: tuple[str, ...] = ("最高學歷", "學歷", "教育程度")
    expected_title: tuple[str, ...] = ("希望職稱", "希望職務", "期望職務", "應徵職務")
    expected_city: tuple[str, ...] = ("希望工作地點", "期望工作地點", "工作地點")


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
    # OCR often drops the colon between a short identity label and its value.
    # Restrict this recovery to a CJK personal-name shape so headings such as
    # "姓名與聯絡資料" cannot consume an arbitrary line.
    cjk_aliases = tuple(item for item in aliases if item.lower() != "name")
    if cjk_aliases:
        joined = "|".join(
            re.escape(item) for item in sorted(cjk_aliases, key=len, reverse=True)
        )
        ocr_value = re.search(
            rf"(?:^|\n)\s*(?:{joined})\s*[：:]?\s*([\u4e00-\u9fff·]{{2,8}})",
            text,
        )
        if ocr_value:
            return ocr_value.group(1), 0.88
    excluded = {"履歷", "自傳", "工作經歷", "技能專長", "學歷", "基本資料"}
    for line in (item.strip() for item in text.splitlines()[:12]):
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", line) and line not in excluded:
            # A leading line is often a city or job title rather than a name;
            # those must not be emitted as a name by this low-confidence path.
            if any(city in line for city in TAIWAN_CITIES):
                continue
            if any(keyword in line for keyword in TITLE_KEYWORDS):
                continue
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
    if city_value:
        city_source = city_value
    else:
        # Without a residence label, only trust a city that begins a line (an
        # address-shaped signal). Scanning the whole document previously
        # surfaced an employer or school location instead of the residence.
        city_source = next(
            (
                stripped
                for stripped in (line.strip() for line in text.splitlines())
                if any(stripped.startswith(name) for name in TAIWAN_CITIES)
            ),
            "",
        )
    # Choose the city appearing earliest in the source, not the one that comes
    # first in the TAIWAN_CITIES ordering.
    city = min(
        (name for name in TAIWAN_CITIES if name in city_source),
        key=city_source.find,
        default=None,
    )
    city = city.replace("臺", "台") if city else None
    title = label(text, rules.title)
    company = label(text, rules.company)
    education_value = label(text, rules.education)
    education = next(
        (
            degree
            for degree in ("博士", "碩士", "研究所", "學士", "大學", "專科", "高職", "高中", "國中")
            if education_value and degree in education_value
        ),
        education_value,
    )
    expected_title = label(text, rules.expected_title)
    # Older board exports sometimes only expose the target title. Preserve the
    # legacy current_title fallback while also retaining its true semantics.
    title = title or expected_title
    expected_city_value = label(text, rules.expected_city, 200)
    expected_cities = (
        sorted(
            {
                city.replace("臺", "台")
                for city in TAIWAN_CITIES
                if city in expected_city_value
            }
        )
        if expected_city_value
        else []
    )
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
    # Keep the original seven-field payload stable for older integrations, but
    # expose additional canonical career fields whenever the source contains
    # an explicit label.  These map directly to Candidate columns on confirm.
    optional_fields = {
        "current_company": (company, 0.88),
        "highest_education": (education, 0.90),
        "expected_title": (expected_title, 0.88),
        "expected_cities": (expected_cities or None, 0.90),
    }
    for field, (value, score) in optional_fields.items():
        if value:
            payload[field] = value
            confidence[field] = score
    return payload, confidence
