"""Pure-function compliance checker for interview questions.

Screens interview questions (whether AI-generated or manually typed) for
potentially unlawful / discriminatory topics under Taiwan employment law,
notably 就業服務法第 5 條 (Employment Service Act, Art. 5) and
性別平等工作法第 7 / 第 11 條 (Act of Gender Equality in Employment,
Art. 7 / 11), which forbid using protected personal attributes in hiring.

This module is intentionally self-contained (no app imports) so it can be
reused by any service or route and unit-tested in isolation. The rule library
is heuristic keyword / regex matching in Traditional Chinese and English; it is
a compliance *aid*, not a legal determination. All wording below must be
reviewed by qualified legal counsel before being relied upon in production.
"""

from __future__ import annotations

import re
from typing import Any, TypedDict

# Bump whenever the rule library or suggestions change so downstream records
# can prove which ruleset produced a given result (存證 / auditability).
COMPLIANCE_RULES_VERSION = "twn-antidiscrimination-2026-07-01"


class ComplianceResult(TypedDict):
    status: str  # "ok" | "warning"
    categories: list[str]
    matched: list[str]
    suggestion: str
    rules_version: str


# category -> rule definition.
# * ``label``: human-readable Traditional Chinese label for the protected topic.
# * ``keywords``: Chinese (and other non-word-boundary) substrings matched literally.
# * ``patterns``: English terms matched case-insensitively with word boundaries
#   to avoid false positives (e.g. "age" must not match "manage"/"message").
# * ``suggestion``: a lawful alternative that redirects toward job-ability.
_RULE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "marital": {
        "label": "婚姻狀況",
        "keywords": [
            "婚姻",
            "已婚",
            "未婚",
            "離婚",
            "結婚",
            "打算結婚",
            "何時結婚",
            "配偶",
            "老公",
            "老婆",
            "感情狀況",
            "有沒有男朋友",
            "有沒有女朋友",
            "有沒有交往",
        ],
        "patterns": ["marital", "married", "spouse", "husband", "wife", "boyfriend", "girlfriend"],
        "suggestion": (
            "建議改問工作能力面向：避免詢問婚姻或感情狀況，"
            "可改問是否能配合職務所需的出差、輪班或加班安排。"
        ),
    },
    "pregnancy": {
        "label": "懷孕或生育計畫",
        "keywords": [
            "懷孕",
            "有孕",
            "生育",
            "生小孩",
            "生子",
            "生寶寶",
            "打算生",
            "備孕",
            "產假",
            "育嬰假",
            "育嬰留職",
            "生育計畫",
            "月經",
            "經期",
        ],
        "patterns": [
            "pregnan\\w*",
            "maternity",
            "childbearing",
            "plan to have (?:a )?(?:child|children|baby|kids)",
        ],
        "suggestion": (
            "建議改問工作能力面向：避免詢問懷孕或生育計畫，"
            "可改問是否能配合職務的工作時間與出勤要求。"
        ),
    },
    "childcare": {
        "label": "家庭照顧責任",
        "keywords": [
            "照顧小孩",
            "照顧家人",
            "照顧長輩",
            "照顧父母",
            "家庭照顧",
            "家庭責任",
            "帶小孩",
            "誰帶小孩",
            "誰顧小孩",
            "托兒",
            "育兒",
            "家裡有沒有小孩",
        ],
        "patterns": [
            "child\\s?care",
            "care for (?:your )?(?:children|family|parents|kids)",
            "caregiving",
            "dependents",
        ],
        "suggestion": (
            "建議改問工作能力面向：避免詢問家庭照顧責任，"
            "可改問是否能配合職務所需的工時、值班或臨時加班。"
        ),
    },
    "age": {
        "label": "年齡",
        "keywords": [
            "年齡",
            "幾歲",
            "今年多大",
            "出生年",
            "出生日期",
            "民國幾年",
            "哪一年出生",
            "生肖",
            "屬什麼",
        ],
        "patterns": ["age", "how old", "year of birth", "birth year", "date of birth", "birthday"],
        "suggestion": (
            "建議改問工作能力面向：避免詢問年齡或出生年次，"
            "可改問與職務相關的經驗年資或具體技能。"
        ),
    },
    "gender": {
        "label": "性別或性傾向",
        "keywords": [
            "性別",
            "性傾向",
            "性向",
            "你是男是女",
            "男生還是女生",
            "同性戀",
            "異性戀",
            "跨性別",
        ],
        "patterns": [
            "gender",
            "sexual orientation",
            "homosexual",
            "heterosexual",
            "transgender",
            "lgbt",
        ],
        "suggestion": (
            "建議改問工作能力面向：避免詢問性別或性傾向，"
            "請聚焦職務所需的專業能力與工作表現。"
        ),
    },
    "race": {
        "label": "種族或籍貫",
        "keywords": [
            "種族",
            "籍貫",
            "省籍",
            "外省",
            "本省",
            "族群",
            "原住民",
            "血統",
            "國籍",
            "你是哪裡人",
            "老家在哪",
            "老家哪裡",
        ],
        "patterns": [
            "race",
            "ethnicity",
            "ethnic",
            "nationality",
            "native place",
            "where are you from",
        ],
        "suggestion": (
            "建議改問工作能力面向：避免詢問種族、籍貫或國籍，"
            "可改問是否具備合法工作資格與職務所需語言能力。"
        ),
    },
    "religion": {
        "label": "宗教或黨派",
        "keywords": [
            "宗教",
            "信仰",
            "拜拜",
            "佛教",
            "基督教",
            "天主教",
            "伊斯蘭",
            "回教",
            "政黨",
            "黨派",
            "政治立場",
            "支持哪一黨",
            "支持哪個政黨",
        ],
        "patterns": ["religion", "religious", "faith", "church", "political party", "which party"],
        "suggestion": (
            "建議改問工作能力面向：避免詢問宗教信仰或政黨黨派，"
            "可改問是否能配合公司既定的工作時間與排班。"
        ),
    },
    "disability_health": {
        "label": "身心障礙或健康病史",
        "keywords": [
            "身心障礙",
            "殘障",
            "殘疾",
            "病史",
            "疾病",
            "健康狀況",
            "健康情形",
            "慢性病",
            "精神疾病",
            "家族病史",
            "遺傳疾病",
            "開過刀",
            "服用藥物",
            "身心狀況",
            "是否生病",
        ],
        "patterns": [
            "disabilit\\w*",
            "handicap\\w*",
            "health condition",
            "medical history",
            "chronic (?:illness|disease)",
            "mental illness",
        ],
        "suggestion": (
            "建議改問工作能力面向：避免詢問健康病史或身心障礙，"
            "可改問是否能執行職務說明書所列的必要工作任務（必要時提供合理調整）。"
        ),
    },
    "appearance": {
        "label": "容貌或身材",
        "keywords": [
            "身高",
            "體重",
            "外貌",
            "長相",
            "五官",
            "容貌",
            "胖瘦",
            "幾公斤",
            "幾公分",
            "整形",
            "身材",
        ],
        "patterns": ["body weight", "physical appearance", "how tall", "your looks"],
        "suggestion": (
            "建議改問工作能力面向：避免針對身高、體重或容貌提問，"
            "請改問與職務績效直接相關的能力；如職務確有外型需求，"
            "須有明確職業資格依據並經法遵確認。"
        ),
    },
    "astrology_blood": {
        "label": "星座、血型或命理",
        "keywords": [
            "星座",
            "血型",
            "命盤",
            "紫微",
            "塔羅",
            "算命",
            "生辰八字",
            "八字",
            "占卜",
        ],
        "patterns": ["astrolog\\w*", "blood type", "horoscope", "zodiac"],
        "suggestion": (
            "建議改問工作能力面向：避免以星座、血型或命理作為評估依據，"
            "請改問可觀察的工作行為與具體成果。"
        ),
    },
}


def _compile_rules() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    compiled: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
    for category, spec in _RULE_DEFINITIONS.items():
        entries: list[tuple[str, re.Pattern[str]]] = []
        for keyword in spec["keywords"]:
            entries.append((keyword, re.compile(re.escape(keyword))))
        for pattern in spec["patterns"]:
            expression = rf"(?<![A-Za-z]){pattern}(?![A-Za-z])"
            entries.append((pattern, re.compile(expression, re.IGNORECASE)))
        compiled[category] = entries
    return compiled


_COMPILED_RULES = _compile_rules()


def category_label(category: str) -> str:
    """Return the Traditional Chinese label for a rule category."""
    spec = _RULE_DEFINITIONS.get(category)
    return spec["label"] if spec else category


def _empty_result() -> ComplianceResult:
    return {
        "status": "ok",
        "categories": [],
        "matched": [],
        "suggestion": "",
        "rules_version": COMPLIANCE_RULES_VERSION,
    }


def check_question(text: object | None) -> ComplianceResult:
    """Screen a single question for unlawful / discriminatory topics.

    Returns a result dict with ``status`` ('ok' or 'warning'), the matched rule
    ``categories``, the ``matched`` surface keywords, a lawful ``suggestion``
    (only when a warning is raised) and the ``rules_version`` used.
    """
    result = _empty_result()
    if text is None:
        return result
    haystack = str(text).strip()
    if not haystack:
        return result

    categories: list[str] = []
    matched: list[str] = []
    suggestions: list[str] = []
    seen_matched: set[str] = set()

    for category, entries in _COMPILED_RULES.items():
        category_hits = [keyword for keyword, pattern in entries if pattern.search(haystack)]
        if not category_hits:
            continue
        categories.append(category)
        suggestions.append(_RULE_DEFINITIONS[category]["suggestion"])
        for keyword in category_hits:
            if keyword not in seen_matched:
                seen_matched.add(keyword)
                matched.append(keyword)

    if categories:
        result["status"] = "warning"
        result["categories"] = categories
        result["matched"] = matched
        result["suggestion"] = " ".join(suggestions)
    return result


def check_questions(texts: list[object | None]) -> list[ComplianceResult]:
    """Batch variant of :func:`check_question`."""
    return [check_question(text) for text in texts]
