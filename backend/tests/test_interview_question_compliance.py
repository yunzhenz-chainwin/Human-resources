"""Unit tests for the interview-question anti-discrimination compliance checker."""

import pytest

from app.services.interview_question_compliance import (
    COMPLIANCE_RULES_VERSION,
    category_label,
    check_question,
    check_questions,
)

# One representative violating question per protected category.
CATEGORY_SAMPLES = {
    "marital": "請問你已婚了嗎？結婚後有打算搬家嗎？",
    "pregnancy": "你最近有懷孕或生小孩的計畫嗎？",
    "childcare": "家裡誰帶小孩？你要照顧家人嗎？",
    "age": "你今年幾歲？是哪一年出生的？",
    "gender": "這個職務想確認一下你的性傾向。",
    "race": "你是哪裡人？籍貫在哪個省份？",
    "religion": "你有什麼宗教信仰？支持哪一黨？",
    "disability_health": "可以說明你的病史與健康狀況嗎？",
    "appearance": "你的身高體重多少？對自己的容貌滿意嗎？",
    "astrology_blood": "你是什麼星座？血型是哪一型？",
}

# Job-relevant questions that must never be flagged.
CLEAN_QUESTIONS = [
    "請用一個實際案例說明你如何完成後端 API 的效能優化。",
    "面對時程壓力時，你如何排序任務並確保交付品質？",
    "請說明你的到職時間、工作地點或型態期待。",
    "你如何帶領團隊在資源有限時仍達成目標？",
    "請分享一次你和意見不同的同事合作並完成任務的經驗。",
    "你累積約 5 年工作經驗，如何拆解超出經驗邊界的任務？",
]


@pytest.mark.parametrize("category, question", list(CATEGORY_SAMPLES.items()))
def test_each_category_is_detected(category: str, question: str) -> None:
    result = check_question(question)
    assert result["status"] == "warning"
    assert category in result["categories"]
    assert result["matched"], "a warning must report the matched keywords"
    assert result["suggestion"], "a warning must provide a lawful alternative"
    assert "工作能力" in result["suggestion"]
    assert result["rules_version"] == COMPLIANCE_RULES_VERSION


@pytest.mark.parametrize("question", CLEAN_QUESTIONS)
def test_clean_questions_are_not_flagged(question: str) -> None:
    result = check_question(question)
    assert result["status"] == "ok"
    assert result["categories"] == []
    assert result["matched"] == []
    assert result["suggestion"] == ""
    assert result["rules_version"] == COMPLIANCE_RULES_VERSION


def test_empty_and_none_are_ok() -> None:
    for value in (None, "", "   "):
        result = check_question(value)
        assert result["status"] == "ok"
        assert result["categories"] == []


def test_multiple_categories_in_one_question() -> None:
    result = check_question("你已婚了嗎？今年幾歲？信什麼宗教？")
    assert result["status"] == "warning"
    assert {"marital", "age", "religion"} <= set(result["categories"])
    # Suggestions from all matched categories are concatenated.
    assert result["suggestion"].count("建議改問工作能力面向") >= 3


def test_english_keywords_use_word_boundaries() -> None:
    # Real English violations are caught (case-insensitive).
    assert check_question("What is your marital status?")["status"] == "warning"
    assert "age" in check_question("How old are you?")["categories"]
    assert "race" in check_question("What is your race?")["categories"]

    # Substrings inside ordinary words must NOT trigger false positives.
    for benign in (
        "How do you manage a message queue on each page?",  # contains 'age'
        "Describe how you embrace grace under pressure.",  # contains 'race'
        "How do you assess a candidate's skills?",  # contains 'sex'? no, 'assess'
    ):
        assert check_question(benign)["status"] == "ok", benign


def test_check_questions_batch_preserves_order() -> None:
    results = check_questions(
        [CLEAN_QUESTIONS[0], CATEGORY_SAMPLES["age"], CLEAN_QUESTIONS[1]]
    )
    assert [item["status"] for item in results] == ["ok", "warning", "ok"]
    assert "age" in results[1]["categories"]


def test_matched_keywords_are_deduplicated() -> None:
    result = check_question("你幾歲？你到底幾歲？年齡多少？")
    assert result["status"] == "warning"
    assert len(result["matched"]) == len(set(result["matched"]))


def test_category_label_returns_chinese_label() -> None:
    assert category_label("pregnancy") == "懷孕或生育計畫"
    assert category_label("unknown_category") == "unknown_category"
