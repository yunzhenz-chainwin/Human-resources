"""Anti-discrimination lint for job requisition text.

This module encodes the protected characteristics that Taiwan employment law
forbids using as recruitment/screening criteria, and provides a pure-function
linter that scans a requisition's title / summary / JD for discriminatory
wording and returns rewrite suggestions.

Legal basis (informational only -- MUST be reviewed by qualified counsel before
relying on it for compliance):

* 就業服務法 (Employment Service Act) 第 5 條第 1 項 -- prohibits discrimination
  in recruitment on the basis of race, class, language, thought, religion,
  political affiliation, place of origin/birth, gender, gender orientation,
  age, marriage, appearance/facial features, disability, star sign/blood type,
  or past membership of a labour union.
* 中高齡者及高齡者就業促進法 (Middle-aged and Elderly Employment Promotion Act)
  -- prohibits age discrimination against workers aged 45+.
* 性別平等工作法 (Act of Gender Equality in Employment) -- prohibits sex /
  gender / marriage / pregnancy discrimination in recruitment.

The dictionary and rules here are heuristic keyword/regex matchers intended to
surface *likely* problems for a human reviewer; they are neither exhaustive nor
authoritative. A "warning" result should prompt review, not block publishing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, TypedDict

# Bump this whenever the rule set below changes. It is a module constant and is
# deliberately NOT persisted to the database -- clients that cache lint results
# can compare it to know when a re-lint is worthwhile.
JD_COMPLIANCE_RULES_VERSION = "2026.07.31"

ComplianceStatus = Literal["ok", "warning"]
JobTextField = Literal["title", "summary", "jd"]

# Category identifiers map to the protected characteristics in 就服法 §5.
ComplianceCategory = Literal[
    "gender",
    "age",
    "marital_pregnancy",
    "military",
    "appearance",
    "nationality_race",
    "religion",
    "disability",
    "astrology",
]


class ComplianceFinding(TypedDict):
    category: ComplianceCategory
    matched: str
    field: JobTextField
    suggestion: str


class ComplianceResult(TypedDict):
    status: ComplianceStatus
    findings: list[ComplianceFinding]


@dataclass(frozen=True)
class _CategoryRule:
    """A protected-characteristic matcher.

    ``pattern`` is applied to each scanned field; every non-overlapping match is
    reported as a finding carrying ``category`` and ``suggestion``.
    """

    category: ComplianceCategory
    label_zh: str
    keywords: tuple[str, ...]  # human-readable examples, for docs / UI hints
    pattern: re.Pattern[str]
    suggestion: str


def _compile(*alts: str) -> re.Pattern[str]:
    # ASCII letters are matched case-insensitively; CJK is unaffected by the flag.
    return re.compile("|".join(alts), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Protected-characteristic dictionary (就服法 §5 receptor list).
#
# Patterns intentionally require a *restrictive* context (限 / 僅限 / 需 / X佳 /
# X優先 / "only") around a sensitive token so that neutral, descriptive mentions
# (e.g. "服務男性客戶", "年滿 18 歲", "不限性別") are not falsely flagged.
# ---------------------------------------------------------------------------
JD_COMPLIANCE_RULES: tuple[_CategoryRule, ...] = (
    _CategoryRule(
        category="gender",
        label_zh="性別",
        keywords=("限男性", "限女性", "男性佳", "女性優先", "male only"),
        pattern=_compile(
            r"(?:限|僅限|只限|限定|需為|徵|招募?|聘)(?:男|女)(?:性|生)?(?:佳|尤佳|優先)?",
            r"(?:男|女)(?:性|生)(?:佳|尤佳|優先|為佳)",
            r"(?:male|female|men|women|gentlem[ae]n|lad(?:y|ies))\s*only",
        ),
        suggestion="本職務不限性別，歡迎符合資格者應徵；請刪除性別限制字眼。",
    ),
    _CategoryRule(
        category="age",
        label_zh="年齡",
        keywords=("限35歲以下", "20-30歲", "年輕有活力", "限應屆", "young"),
        pattern=_compile(
            r"限?\s*\d{1,2}\s*[-~至到]\s*\d{1,2}\s*歲",
            r"\d{1,2}\s*歲(?:以下|以內)",
            r"限\s*\d{1,2}\s*歲",
            r"年齡\s*\d{1,2}",
            r"年輕有活力|年輕族群|限年輕|需年輕|要年輕|年紀輕",
            r"限應屆|應屆(?:畢業生?)?(?:佳|優先)|僅招應屆",
            r"under\s*\d{1,2}\b|recent\s+graduates?\s+only|\byoung\b",
        ),
        suggestion="本職務不限年齡，請以工作所需的能力與經驗描述資格條件，勿設定年齡上限或偏好。",
    ),
    _CategoryRule(
        category="marital_pregnancy",
        label_zh="婚姻／懷孕生育",
        keywords=("限未婚", "已婚者佳", "無家庭負擔", "無生育計畫", "single preferred"),
        pattern=_compile(
            r"限未婚|需未婚|限已婚|需已婚|未婚(?:者|佳|優先)|已婚者?(?:佳|優先)",
            r"單身(?:佳|優先)|限單身",
            r"無家庭(?:負擔|牽絆|因素)",
            r"無(?:生育|懷孕)(?:計[畫劃]|規劃|問題)?",
            r"不得(?:懷孕|生育)|懷孕者?(?:勿|不得|不可)",
            r"(?:married|single|unmarried)\s+(?:only|preferred)",
        ),
        suggestion="不得以婚姻、懷孕或生育狀況作為條件，請刪除相關限制。",
    ),
    _CategoryRule(
        category="military",
        label_zh="兵役",
        keywords=("需役畢", "限役畢", "役畢優先", "退伍者優先"),
        pattern=_compile(
            r"需役畢|限役畢|須役畢|役畢(?:者)?(?:佳|優先)",
            r"免役者?(?:勿|不得|不可)",
            r"需服完兵役|已服(?:完)?兵役者?(?:佳|優先)?",
            r"限退伍|退伍者?優先",
            r"military\s+service\s+(?:required|completed)",
        ),
        suggestion="兵役狀況不得作為應徵條件；若有實際出勤或到職時間需求，請改以『可配合到職時間』描述。",
    ),
    _CategoryRule(
        category="appearance",
        label_zh="容貌／體格",
        keywords=("體貌端正", "五官端正", "形象佳", "限身高", "good looking"),
        pattern=_compile(
            r"體貌端正|五官端正|相貌端正|面貌姣好|眉清目秀",
            r"形象[佳好]|外[型形貌][佳好]|外貌[佳好]|儀表[佳好]",
            r"限身高|需身高|身高\s*\d{2,3}\s*(?:公分|cm|以上)?",
            r"體態勻稱|身材[佳好]",
            r"good[\s-]?looking|attractive\s+appearance",
        ),
        suggestion="除非為職務真實必要，不得要求特定容貌、身高或外型，請刪除相關條件。",
    ),
    _CategoryRule(
        category="nationality_race",
        label_zh="國籍／出生地／種族",
        keywords=("限本國籍", "限台灣人", "不收外籍", "citizens only"),
        pattern=_compile(
            r"限本國籍|需本國籍|限本國人|限台灣人|限本地人|純本國|限華人|限漢人",
            r"不[收招用]外籍|外籍者?(?:勿|不得|不可)",
            r"限(?:本地|在地)出生",
            r"(?:local(?:s)?|citizens?|nationals?)\s+only",
        ),
        suggestion="不得限制國籍、出生地或種族；若職務需合法工作權，請改為『須具備在台合法工作權』。",
    ),
    _CategoryRule(
        category="religion",
        label_zh="宗教信仰",
        keywords=("限佛教", "須為教徒", "需信奉", "christian only"),
        pattern=_compile(
            r"限(?:佛|道|基督|天主|回|伊斯蘭|穆斯林|猶太)教?徒?",
            r"需為.{0,4}教徒|須為.{0,4}教徒|須信仰",
            r"不[收招用].{0,4}教徒",
            r"限有(?:宗教)?信仰|限無神論",
            r"(?:christian|muslim|buddhist)\s+only",
        ),
        suggestion="不得限制宗教信仰，請刪除相關條件。",
    ),
    _CategoryRule(
        category="disability",
        label_zh="身心障礙／健康",
        keywords=("四肢健全", "身體健康無疾病", "無重大疾病", "able-bodied"),
        pattern=_compile(
            r"四肢健全|肢體健全|身體健全",
            r"無身心障礙|非身心障礙",
            r"(?:需|限|須)身體健康|健康無虞",
            r"無重大疾病|無傳染病者?(?:佳|優先)?",
            r"able[\s-]?bodied|no\s+disabilit(?:y|ies)",
        ),
        suggestion="不得以身心障礙或健康狀況排除應徵者；如有職務真實體能需求，請具體描述該項工作內容。",
    ),
    _CategoryRule(
        category="astrology",
        label_zh="星座／血型／生肖",
        keywords=("限特定星座", "血型", "生肖", "blood type"),
        pattern=_compile(
            r"限?[^\S\r\n]{0,2}星座|(?:需|限|忌)[^\S\r\n]{0,2}血型|血型\s*[ABO]",
            r"星座\s*[限需]|(?:需|限)生肖",
            r"zodiac|blood\s*type",
        ),
        suggestion="不得以星座、血型或生肖等與工作無關的特徵作為條件，請刪除。",
    ),
)


def _scan_field(field: JobTextField, text: str) -> list[ComplianceFinding]:
    findings: list[ComplianceFinding] = []
    seen: set[tuple[str, str]] = set()
    for rule in JD_COMPLIANCE_RULES:
        for match in rule.pattern.finditer(text):
            matched = match.group(0).strip()
            if not matched:
                continue
            key = (rule.category, matched.casefold())
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                ComplianceFinding(
                    category=rule.category,
                    matched=matched,
                    field=field,
                    suggestion=rule.suggestion,
                )
            )
    return findings


def lint_job_text(
    *,
    title: str | None = None,
    summary: str | None = None,
    jd: str | None = None,
) -> ComplianceResult:
    """Scan requisition text for discriminatory wording.

    Returns ``{"status": "ok"|"warning", "findings": [...]}``. ``warning`` means
    at least one protected-characteristic hit was found; it is advisory and does
    not, by itself, block saving the requisition.
    """
    findings: list[ComplianceFinding] = []
    for field, value in (("title", title), ("summary", summary), ("jd", jd)):
        if value:
            findings.extend(_scan_field(field, value))  # type: ignore[arg-type]
    status: ComplianceStatus = "warning" if findings else "ok"
    return ComplianceResult(status=status, findings=findings)
