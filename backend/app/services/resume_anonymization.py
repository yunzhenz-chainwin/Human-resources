import re
from dataclasses import dataclass

from app.schemas.privacy import AnonymizedField, ResumeAnonymizationSummary

_FIELDS: tuple[AnonymizedField, ...] = (
    "name",
    "address",
    "phone",
    "email",
    "birth_date",
    "national_id",
    "personal_url",
)

_PLACEHOLDERS: dict[AnonymizedField, str] = {
    "name": "[NAME REDACTED]",
    "address": "[ADDRESS REDACTED]",
    "phone": "[PHONE REDACTED]",
    "email": "[EMAIL REDACTED]",
    "birth_date": "[BIRTH DATE REDACTED]",
    "national_id": "[ID REDACTED]",
    "personal_url": "[URL REDACTED]",
}

_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}(?![\w.-])",
    re.IGNORECASE,
)
_MOBILE_RE = re.compile(
    r"(?<![\dA-Za-z])(?:09\d{2}(?:[ .-]?\d){6}|(?:\+?886)[ .-]?9\d{2}(?:[ .-]?\d){6})(?!\d)"
)
_LANDLINE_RE = re.compile(
    r"(?<![\dA-Za-z])0[2-8](?:[ .-]?\d){7,8}(?:\s*(?:#|ext\.?|分機)\s*\d{1,6})?(?!\d)",
    re.IGNORECASE,
)
_NATIONAL_ID_RE = re.compile(r"(?<![A-Z0-9])[A-Z][12]\d{8}(?![A-Z0-9])", re.IGNORECASE)
_URL_RE = re.compile(
    r"(?<![@\w])(?:https?://|www\.)[^\s<>\"'，。；、]+",
    re.IGNORECASE,
)
_NAME_LABEL_RE = re.compile(
    r"(?im)^[ \t]*(?:求職者姓名|姓名|名字|full[ \t]+name|name)[ \t]*[:：][ \t]*"
    r"(?P<value>[^\r\n|；;，,]{1,100})"
)
_ADDRESS_LABEL_RE = re.compile(
    r"(?im)^[ \t]*(?:居住地址|通訊地址|戶籍地址|聯絡地址|地址|mailing[ \t]+address|address)"
    r"[ \t]*[:：][ \t]*(?P<value>[^\r\n|]{3,255})"
)
_TAIWAN_ADDRESS_RE = re.compile(
    r"(?<![\w])(?:(?:臺|台)北市|新北市|桃園市|(?:臺|台)中市|(?:臺|台)南市|高雄市|基隆市|"
    r"新竹市|嘉義市|宜蘭縣|新竹縣|苗栗縣|彰化縣|南投縣|雲林縣|嘉義縣|屏東縣|"
    r"花蓮縣|(?:臺|台)東縣|澎湖縣|金門縣|連江縣)"
    r"[^\r\n,，;；|]{2,100}?(?:\d+[之-]?\d*號(?:\d+[樓Ff])?)"
)
_BIRTH_DATE_LABEL_RE = re.compile(
    r"(?im)(?:出生日期|出生年月日|生日|birth[ \t]*date|date[ \t]+of[ \t]+birth)"
    r"[ \t]*[:：]?[ \t]*(?P<value>(?:民國[ \t]*)?\d{2,4}[年/.-]\d{1,2}(?:[月/.-]\d{1,2}日?)?)"
)
_CJK_HEADER_NAME_RE = re.compile(
    r"[王李張劉陳楊黃趙吳周徐孫馬朱胡郭何高林羅鄭梁謝宋唐許韓馮鄧曹彭曾肖蕭田"
    r"董袁潘于蔣蔡余杜葉程蘇魏呂丁任沈姚盧姜崔鍾譚陸汪范金石廖賈夏韋傅方白"
    r"鄒孟熊秦邱江尹薛閻段雷侯龍史陶黎賀顧毛郝龔邵萬錢嚴覃武戴莫孔向湯][\u3400-\u9fff]{1,3}"
)
_ENGLISH_HEADER_NAME_RE = re.compile(
    r"[A-Za-z][A-Za-z'-]{1,30}(?:[ \t]+[A-Za-z][A-Za-z'-]{1,30}){1,3}"
)
_NON_NAME_HEADER_WORDS = frozenset(
    {
        "resume",
        "curriculum",
        "vitae",
        "profile",
        "contact",
        "information",
        "engineer",
        "developer",
        "manager",
        "analyst",
        "designer",
        "director",
        "specialist",
    }
)


@dataclass(frozen=True)
class _SensitiveSpan:
    start: int
    end: int
    field: AnonymizedField


@dataclass(frozen=True)
class AnonymizationResult:
    anonymized_text: str
    summary: ResumeAnonymizationSummary


def _trimmed_span(match: re.Match[str], group: str = "value") -> tuple[int, int, str]:
    value = match.group(group)
    leading = len(value) - len(value.lstrip())
    trailing = len(value) - len(value.rstrip())
    start = match.start(group) + leading
    end = match.end(group) - trailing
    return start, end, value.strip()


def _literal_spans(text: str, value: str, field: AnonymizedField) -> list[_SensitiveSpan]:
    flags = re.IGNORECASE if value.isascii() else 0
    return [
        _SensitiveSpan(match.start(), match.end(), field)
        for match in re.finditer(re.escape(value), text, flags)
    ]


def _detected_labeled_values(
    text: str,
    pattern: re.Pattern[str],
    field: AnonymizedField,
) -> tuple[list[_SensitiveSpan], list[str]]:
    spans: list[_SensitiveSpan] = []
    values: list[str] = []
    for match in pattern.finditer(text):
        start, end, value = _trimmed_span(match)
        if start < end:
            spans.append(_SensitiveSpan(start, end, field))
            values.append(value)
    return spans, values


def _select_non_overlapping(spans: list[_SensitiveSpan]) -> list[_SensitiveSpan]:
    # Longest match wins when two detectors start at the same position. This keeps,
    # for example, an entire labelled address from being split by a phone-like number.
    ordered = sorted(spans, key=lambda item: (item.start, -(item.end - item.start)))
    selected: list[_SensitiveSpan] = []
    last_end = -1
    for span in ordered:
        if span.start < last_end or span.start >= span.end:
            continue
        selected.append(span)
        last_end = span.end
    return selected


def _header_name_spans(text: str) -> list[_SensitiveSpan]:
    """Conservatively recognize an unlabelled name near a resume header."""

    context = text[:2_000].casefold()
    context_markers = (
        "履歷",
        "resume",
        "email",
        "e-mail",
        "手機",
        "電話",
        "phone",
        "地址",
        "address",
        "學歷",
        "education",
        "經歷",
        "experience",
    )
    if sum(marker in context for marker in context_markers) < 2:
        return []

    nonempty = [
        match
        for match in re.finditer(r"(?m)^[ \t]*(?P<value>[^\r\n]{2,100}?)[ \t]*$", text[:2_000])
        if match.group("value").strip()
    ][:6]
    for match in nonempty:
        start, end, value = _trimmed_span(match)
        if ":" in value or "：" in value:
            continue
        if _CJK_HEADER_NAME_RE.fullmatch(value):
            return [_SensitiveSpan(start, end, "name")]
        if _ENGLISH_HEADER_NAME_RE.fullmatch(value):
            words = {word.casefold() for word in re.findall(r"[A-Za-z]+", value)}
            if words.isdisjoint(_NON_NAME_HEADER_WORDS):
                return [_SensitiveSpan(start, end, "name")]
    return []


def anonymize_resume_text(
    plain_text: str,
    *,
    additional_names: list[str] | None = None,
    additional_addresses: list[str] | None = None,
) -> AnonymizationResult:
    """Redact obvious PII from plain text without retaining any source value."""

    spans: list[_SensitiveSpan] = []
    header_name_spans = _header_name_spans(plain_text)
    spans.extend(header_name_spans)
    name_spans, detected_names = _detected_labeled_values(plain_text, _NAME_LABEL_RE, "name")
    address_spans, detected_addresses = _detected_labeled_values(
        plain_text, _ADDRESS_LABEL_RE, "address"
    )
    spans.extend(name_spans)
    spans.extend(address_spans)

    # A labelled value commonly appears again in summaries and cover letters. Once
    # found, redact all exact occurrences without ever returning or persisting it.
    header_names = [plain_text[span.start : span.end] for span in header_name_spans]
    for value in [*header_names, *detected_names, *(additional_names or [])]:
        spans.extend(_literal_spans(plain_text, value, "name"))
    for value in [*detected_addresses, *(additional_addresses or [])]:
        spans.extend(_literal_spans(plain_text, value, "address"))

    for pattern, field in (
        (_TAIWAN_ADDRESS_RE, "address"),
        (_EMAIL_RE, "email"),
        (_MOBILE_RE, "phone"),
        (_LANDLINE_RE, "phone"),
        (_NATIONAL_ID_RE, "national_id"),
        (_URL_RE, "personal_url"),
    ):
        spans.extend(
            _SensitiveSpan(match.start(), match.end(), field)
            for match in pattern.finditer(plain_text)
        )
    for match in _BIRTH_DATE_LABEL_RE.finditer(plain_text):
        start, end, _ = _trimmed_span(match)
        spans.append(_SensitiveSpan(start, end, "birth_date"))

    selected = _select_non_overlapping(spans)
    field_counts: dict[AnonymizedField, int] = dict.fromkeys(_FIELDS, 0)
    parts: list[str] = []
    cursor = 0
    for span in selected:
        parts.append(plain_text[cursor : span.start])
        parts.append(_PLACEHOLDERS[span.field])
        cursor = span.end
        field_counts[span.field] += 1
    parts.append(plain_text[cursor:])
    anonymized = "".join(parts)
    return AnonymizationResult(
        anonymized_text=anonymized,
        summary=ResumeAnonymizationSummary(
            field_counts=field_counts,
            total_replacements=len(selected),
            input_characters=len(plain_text),
            output_characters=len(anonymized),
        ),
    )
