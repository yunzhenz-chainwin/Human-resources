import hashlib
import json
import re
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.schemas.interview_questions import (
    InterviewQuestionPlanItem,
    SuggestedInterviewQuestion,
    TraitQuestionSuggestion,
)

HR_STANDARD_QUESTIONS = (
    (
        "求職動機",
        "請用三分鐘介紹自己，並說明這次轉職最主要的原因。",
        "確認轉職動機、表達結構與職涯方向。",
        "這次選擇新工作的三個優先條件是什麼？",
    ),
    (
        "職務期待",
        "你為什麼想加入我們公司？你對這份工作的期待是什麼？",
        "確認候選人是否理解機會內容，並對期待進行對焦。",
        "哪些工作內容會讓你最有投入感？",
    ),
    (
        "合作溝通",
        "請分享一次你和意見不同的同事合作，最後仍完成目標的經驗。",
        "了解溝通、傾聽、處理分歧與共同交付的方式。",
        "你當時具體調整了什麼？結果如何？",
    ),
    (
        "壓力應對",
        "請分享一次工作遇到重大困難或時程壓力時，你如何處理。",
        "了解優先排序、求援、責任感及面對挫折的方式。",
        "如果再做一次，你會改變哪一個做法？",
    ),
    (
        "到職條件",
        "請說明你的到職時間、工作地點或型態期待，以及目前還需要確認的條件。",
        "完成非歧視性的基本任用條件確認，降低後續資訊落差。",
        "如果雙方適合，最早何時可以進入下一步？",
    ),
)


def _clean_context(value: object | None, limit: int = 80) -> str | None:
    if value is None:
        return None
    clean = " ".join(str(value).split())
    return clean[:limit] if clean else None


def _question(
    category: str,
    question: str,
    purpose: str,
    follow_up: str,
    source: str,
) -> InterviewQuestionPlanItem:
    return InterviewQuestionPlanItem(
        category=category,
        question=question,
        purpose=purpose,
        follow_up=follow_up,
        source=source,
    )


def standard_hr_question_plan() -> list[InterviewQuestionPlanItem]:
    """Return the same five fair, job-neutral screening questions for every applicant."""

    return [
        _question(category, question, purpose, follow_up, "全公司 HR 固定題")
        for category, question, purpose, follow_up in HR_STANDARD_QUESTIONS
    ]


def personalized_manager_question_plan(
    *,
    job_title: str,
    current_title: str | None = None,
    total_years: object | None = None,
    candidate_skills: list[str] | None = None,
    required_skills: list[str] | None = None,
    experiences: list[dict[str, object | None]] | None = None,
) -> tuple[list[InterviewQuestionPlanItem], list[str]]:
    """Build five deterministic, auditable questions from role and resume facts."""

    role = _clean_context(job_title, 100) or "此職位"
    title = _clean_context(current_title, 100)
    years = _clean_context(total_years, 20)
    skills = [value for item in (candidate_skills or []) if (value := _clean_context(item, 60))]
    wanted = [value for item in (required_skills or []) if (value := _clean_context(item, 60))]
    experience_rows = experiences or []
    latest = experience_rows[0] if experience_rows else None
    latest_title = _clean_context(latest.get("title"), 100) if latest else None
    latest_company = _clean_context(latest.get("company"), 100) if latest else None
    latest_description = _clean_context(latest.get("description"), 120) if latest else None

    basis = [f"應徵職位：{role}"]
    if title:
        basis.append(f"目前職稱：{title}")
    if years:
        basis.append(f"總年資：{years} 年")
    if skills:
        basis.append(f"候選人技能：{'、'.join(skills[:4])}")
    if latest_title:
        latest_label = f"{latest_company}／{latest_title}" if latest_company else latest_title
        basis.append(f"最近經歷：{latest_label}")

    if title:
        transition_question = (
            f"你目前的職務是「{title}」。其中哪些經驗最能轉移到「{role}」，"
            "又有哪些能力需要重新建立？"
        )
        transition_source = f"目前職稱：{title} × 應徵職位：{role}"
    else:
        transition_question = f"請挑一段最相關的經驗，說明它如何證明你能勝任「{role}」。"
        transition_source = f"應徵職位：{role}"

    normalized_wanted = {item.casefold(): item for item in wanted}
    shared_skill = next((item for item in skills if item.casefold() in normalized_wanted), None)
    focus_skill = shared_skill or (skills[0] if skills else (wanted[0] if wanted else None))
    if focus_skill and focus_skill in skills:
        skill_question = (
            f"你的資料列出「{focus_skill}」。請用一個實際案例說明你在什麼情境使用它、"
            "做了哪些關鍵判斷，以及成果如何衡量。"
        )
        skill_source = f"候選人技能：{focus_skill}"
    elif focus_skill:
        skill_question = (
            f"「{role}」需要「{focus_skill}」。你目前有哪些相近能力，會如何在到職後快速補足？"
        )
        skill_source = f"職缺技能：{focus_skill}"
    else:
        skill_question = f"請說明你完成「{role}」核心工作時，最常使用的專業方法與判斷標準。"
        skill_source = f"應徵職位：{role}"

    if latest_title:
        company_phrase = f"在「{latest_company}」" if latest_company else "在最近一份工作中"
        experience_question = (
            f"你{company_phrase}擔任「{latest_title}」時，哪一項成果最能代表你的能力？"
            "請說明你的責任、行動與可驗證結果。"
        )
        if latest_description:
            experience_question += (
                f" 現有資料提到「{latest_description}」，也請補充你實際負責的範圍。"
            )
        company_label = f"{latest_company}／" if latest_company else ""
        experience_source = f"最近經歷：{company_label}{latest_title}"
    else:
        experience_question = (
            f"請分享一個和「{role}」最接近的專案，說明你的責任、關鍵決策與可驗證結果。"
        )
        experience_source = f"應徵職位：{role}"

    skill_keys = {item.casefold() for item in skills}
    missing_skill = next((item for item in wanted if item.casefold() not in skill_keys), None)
    if missing_skill:
        gap_question = (
            f"職缺資料需要「{missing_skill}」，但現有履歷尚未明確列出。"
            "你是否有相關經驗？若沒有，會如何規劃上手與驗證成果？"
        )
        gap_source = f"履歷與職缺差距：{missing_skill}"
    elif years:
        gap_question = (
            f"你累積約 {years} 年工作經驗。面對「{role}」超出既有經驗邊界的任務時，"
            "你會如何拆解、求援並控管風險？"
        )
        gap_source = f"總年資：{years} 年 × 應徵職位：{role}"
    else:
        gap_question = (
            f"「{role}」工作中若遇到你沒有做過的任務，你會如何在有限時間內學會並交付？"
        )
        gap_source = f"應徵職位：{role}"

    questions = [
        _question(
            "經驗轉移",
            transition_question,
            "確認過往背景與目標職位間的可轉移能力及自我覺察。",
            "請區分你親自負責、協作完成與尚未接觸的部分。",
            transition_source,
        ),
        _question(
            "專業能力",
            skill_question,
            "以具體案例驗證履歷技能，而非只依賴自我評述。",
            "當時有哪些限制？你如何判斷方法有效？",
            skill_source,
        ),
        _question(
            "成果深挖",
            experience_question,
            "釐清候選人在最近經歷中的真實貢獻與成果證據。",
            "結果可用哪些數字、交付物或利害關係人回饋佐證？",
            experience_source,
        ),
        _question(
            "能力風險",
            gap_question,
            "主動確認職缺要求與現有資料間的落差及補足方式。",
            "你會在第 30、60、90 天分別完成什麼？",
            gap_source,
        ),
        _question(
            "到職情境",
            (
                f"假設你明天加入並負責「{role}」，前 90 天你會先了解什麼、"
                "交付什麼，如何和團隊確認優先順序？"
            ),
            "評估候選人對目標職位的理解、規劃與跨角色合作方式。",
            "如果資源只有預期的一半，你會保留哪一項交付？",
            f"應徵職位：{role}",
        ),
    ]
    return questions, basis


def _redact_resume_context(value: object | None, limit: int = 500) -> str | None:
    """Keep Gemini context job-relevant and remove common direct identifiers."""
    clean = _clean_context(value, limit)
    if not clean:
        return None
    clean = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", clean)
    clean = re.sub(r"(?<!\d)(?:\+?886[-\s]?)?0?9\d{2}[-\s]?\d{3}[-\s]?\d{3}(?!\d)", "[PHONE]", clean)
    return clean


def _gemini_prompt(
    *,
    job_title: str,
    current_title: str | None,
    total_years: object | None,
    candidate_skills: list[str],
    required_skills: list[str],
    experiences: list[dict[str, object | None]],
) -> str:
    resume = {
        "current_title": _redact_resume_context(current_title, 100),
        "total_years": _redact_resume_context(total_years, 30),
        "skills": [_redact_resume_context(item, 80) for item in candidate_skills[:12]],
        "experiences": [
            {
                "title": _redact_resume_context(item.get("title"), 100),
                "description": _redact_resume_context(item.get("description"), 500),
            }
            for item in experiences[:6]
        ],
    }
    return (
        "你是資深面試設計師。請根據職位與候選人去識別化履歷，設計部門主管面試題。\n"
        "固定評估框架（每個面向一題）：職務轉移、核心技能、實際成果、問題解決/風險、情境判斷。\n"
        "題目必須以履歷中的具體經歷為依據；不同履歷應產生不同情境，但評估面向與難度保持一致。\n"
        "不得詢問年齡、性別、婚姻、宗教、健康、住址、國籍等非工作必要資訊。\n"
        "只輸出 JSON 陣列，不要 Markdown。每個元素包含 category、question、purpose、follow_up、source。\n"
        f"應徵職位：{_redact_resume_context(job_title, 120)}\n"
        f"職務必要技能：{json.dumps(required_skills[:12], ensure_ascii=False)}\n"
        f"候選人履歷摘要：{json.dumps(resume, ensure_ascii=False)}"
    )


def _parse_gemini_questions(payload: dict[str, Any]) -> list[InterviewQuestionPlanItem] | None:
    try:
        candidates = payload["candidates"]
        text = candidates[0]["content"]["parts"][0]["text"]
        data = json.loads(text.strip().removeprefix("```json").removesuffix("```").strip())
        if not isinstance(data, list) or len(data) != 5:
            return None
        result: list[InterviewQuestionPlanItem] = []
        for item in data:
            if not isinstance(item, dict):
                return None
            values = {key: _clean_context(item.get(key), 1000 if key == "question" else 400) for key in (
                "category", "question", "purpose", "follow_up", "source"
            )}
            if not all(values.values()):
                return None
            result.append(InterviewQuestionPlanItem(**values, source=f"Gemini 動態題目｜{values['source']}"))
        return result
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None


_GEMINI_PLAN_CACHE: dict[str, tuple[float, list[InterviewQuestionPlanItem]]] = {}
_GEMINI_PLAN_CACHE_TTL_SECONDS = 24 * 60 * 60
_GEMINI_QUOTA_COOLDOWN_UNTIL = 0.0
_GEMINI_QUOTA_COOLDOWN_SECONDS = 15 * 60


def _gemini_plan_cache_key(
    *, model: str, job_title: str, current_title: str | None, total_years: object | None,
    candidate_skills: list[str], required_skills: list[str], experiences: list[dict[str, object | None]],
) -> str:
    payload = json.dumps({
        "model": model, "job_title": job_title, "current_title": current_title,
        "total_years": total_years, "candidate_skills": candidate_skills,
        "required_skills": required_skills, "experiences": experiences,
    }, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def gemini_manager_question_plan(
    *,
    job_title: str,
    current_title: str | None = None,
    total_years: object | None = None,
    candidate_skills: list[str] | None = None,
    required_skills: list[str] | None = None,
    experiences: list[dict[str, object | None]] | None = None,
) -> tuple[list[InterviewQuestionPlanItem], list[str], str]:
    """Generate per-candidate manager questions with Gemini, falling back safely.

    Returns questions, personalization basis and generation mode (``gemini`` or
    ``rules``). Gemini is opt-in via GEMINI_ENABLED=true and GEMINI_API_KEY.
    """
    global _GEMINI_QUOTA_COOLDOWN_UNTIL
    skills = candidate_skills or []
    wanted = required_skills or []
    experience_rows = experiences or []
    fallback, basis = personalized_manager_question_plan(
        job_title=job_title,
        current_title=current_title,
        total_years=total_years,
        candidate_skills=skills,
        required_skills=wanted,
        experiences=experience_rows,
    )
    settings = get_settings()
    if not settings.gemini_enabled or not settings.gemini_api_key:
        return fallback, basis, "rules"
    if time.time() < _GEMINI_QUOTA_COOLDOWN_UNTIL:
        return fallback, basis + ["GEMINI_QUOTA_EXCEEDED"], "rules"
    cache_key = _gemini_plan_cache_key(
        model=settings.gemini_model,
        job_title=job_title,
        current_title=current_title,
        total_years=total_years,
        candidate_skills=skills,
        required_skills=wanted,
        experiences=experience_rows,
    )
    cached = _GEMINI_PLAN_CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _GEMINI_PLAN_CACHE_TTL_SECONDS:
        return list(cached[1]), basis + ["Gemini：使用 24 小時快取，未重複呼叫 API"], "gemini"
    if cached:
        _GEMINI_PLAN_CACHE.pop(cache_key, None)
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    body = {
        "contents": [{"parts": [{"text": _gemini_prompt(
            job_title=job_title,
            current_title=current_title,
            total_years=total_years,
            candidate_skills=skills,
            required_skills=wanted,
            experiences=experience_rows,
        )}]}],
        "generationConfig": {"temperature": 0.25, "responseMimeType": "application/json"},
    }
    try:
        with httpx.Client(timeout=settings.gemini_timeout_seconds) as client:
            response = client.post(endpoint, json=body)
            response.raise_for_status()
            questions = _parse_gemini_questions(response.json())
            if questions:
                _GEMINI_PLAN_CACHE[cache_key] = (time.time(), list(questions))
                return questions, basis + ["Gemini：依去識別化履歷與職位動態生成"], "gemini"
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            _GEMINI_QUOTA_COOLDOWN_UNTIL = time.time() + _GEMINI_QUOTA_COOLDOWN_SECONDS
            return fallback, basis + ["GEMINI_QUOTA_EXCEEDED"], "rules"
    except (httpx.HTTPError, ValueError, json.JSONDecodeError):
        pass
    return fallback, basis + ["Gemini：服務不可用，已使用規則式備援"], "rules"

_CATEGORY_KEYWORDS = {
    "conscientiousness": (
        "細心",
        "謹慎",
        "負責",
        "完美",
        "detail",
        "conscient",
        "responsib",
    ),
    "extraversion": ("外向", "社交", "健談", "extrav", "outgoing", "sociable"),
    "introversion": ("內向", "安靜", "沉穩", "introver", "reserved", "quiet"),
    "openness": ("開放", "創意", "創新", "好奇", "open", "creative", "curious"),
    "collaboration": (
        "親和",
        "合作",
        "同理",
        "團隊",
        "agreeab",
        "collabor",
        "empathy",
        "team",
    ),
    "resilience": (
        "抗壓",
        "穩定",
        "韌性",
        "情緒",
        "resilien",
        "stable",
        "stress",
    ),
    "leadership": ("領導", "主導", "決斷", "leader", "decisive", "initiative"),
    "adaptability": ("適應", "彈性", "應變", "adapt", "flexib", "agile"),
}


def _category(trait: str) -> str:
    normalized = trait.casefold()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in normalized for keyword in keywords):
            return category
    return "generic"


def _templates(category: str, trait: str, title: str) -> list[tuple[str, str, str]]:
    role = title.strip()
    common = {
        "conscientiousness": [
            (
                f"請分享你在「{role}」工作中，如何發現並修正一個容易被忽略的細節？",
                "確認細節意識是否能轉化為可驗證的工作行為。",
                "你用了什麼檢查方法，最後避免了什麼影響？",
            ),
            (
                f"當「{role}」任務同時有品質與時程壓力時，你如何取捨？",
                "了解候選人如何在完整度、風險與交付速度間做判斷。",
                "若時間再縮短一半，你會保留哪些檢查？",
            ),
            (
                "請舉例說明你曾為重複性工作建立什麼品質控管機制。",
                "確認特質不只依賴個人努力，也能形成可重複流程。",
                "你如何衡量這個機制真的有效？",
            ),
        ],
        "extraversion": [
            (
                f"在「{role}」需要主動協調陌生利害關係人時，你通常怎麼開啟對話？",
                "了解主動溝通能否用於角色所需的協作情境。",
                "遇到對方不回應時，你會怎麼推進？",
            ),
            (
                "請分享一次你透過口頭溝通化解誤解的經驗。",
                "確認溝通方式是否包含傾聽、澄清與結果追蹤。",
                "你怎麼確認雙方最後理解一致？",
            ),
            (
                "當會議中多數人尚未表態時，你會如何促成有效討論？",
                "評估候選人能否在活躍參與之外，也為他人留出空間。",
                "你如何避免自己的意見主導整場會議？",
            ),
        ],
        "introversion": [
            (
                f"在「{role}」需要臨時公開表達時，你會如何準備並確保重點清楚？",
                "了解候選人如何運用準備與結構化思考完成溝通。",
                "資訊不完整、無法充分準備時你會怎麼做？",
            ),
            (
                "請分享一次你先觀察與傾聽，最後提出關鍵建議的經驗。",
                "確認沉思型工作方式是否能形成具體貢獻。",
                "你如何判斷何時應該提出意見？",
            ),
            (
                "你偏好用哪些方式與團隊同步進度？為什麼？",
                "了解候選人的協作節奏及其對團隊透明度的影響。",
                "團隊偏好即時口頭溝通時，你會如何調整？",
            ),
        ],
        "openness": [
            (
                f"請分享你曾在「{role}」相關工作中嘗試新方法並驗證成效的經驗。",
                "確認創新傾向是否包含假設、實驗與結果，而非只追求新奇。",
                "若實驗失敗，你如何決定調整或停止？",
            ),
            (
                "面對與你原先想法相反的新證據時，你如何處理？",
                "了解候選人是否能更新判斷並清楚說明原因。",
                "請舉一個你因此改變決策的實例。",
            ),
            (
                f"如果加入「{role}」後要改善一項既有流程，你會先了解哪些事情？",
                "評估探索新方案前是否先理解限制、使用者與成功標準。",
                "你會用什麼低成本方式先驗證？",
            ),
        ],
        "collaboration": [
            (
                f"請分享你在「{role}」工作中與意見不同的夥伴共同交付成果的經驗。",
                "了解合作是否包含處理分歧，而不只是維持和諧。",
                "你們最後如何決定採用哪個方案？",
            ),
            (
                "當同事的工作延誤並影響你時，你會怎麼處理？",
                "評估同理心、責任界線與推進結果的平衡。",
                "若相同情況重複發生，你會採取什麼不同做法？",
            ),
            (
                "請舉例說明你如何讓較少發言的團隊成員也能提供意見。",
                "確認候選人能建立包容且有效的協作方式。",
                "這些意見後來如何影響決策？",
            ),
        ],
        "resilience": [
            (
                f"請分享你在「{role}」高壓情境下仍維持品質的一次經驗。",
                "了解候選人的優先排序、求援與風險管理方式。",
                "當時有哪些早期警訊，你如何處理？",
            ),
            (
                "收到出乎預期的負面回饋時，你通常如何回應？",
                "確認情緒調節後能否轉化為具體改善。",
                "請舉例說明那次回饋後你改變了什麼。",
            ),
            (
                "當重要方案失敗時，你如何復盤並決定下一步？",
                "評估面對挫折時的學習能力與責任感。",
                "你如何區分個人責任與系統問題？",
            ),
        ],
        "leadership": [
            (
                f"請分享你在「{role}」相關任務中，在沒有正式職權下推動他人的經驗。",
                "確認影響力是否建立在目標、證據與協作上。",
                "哪一位利害關係人最難取得支持？你怎麼做？",
            ),
            (
                "資訊不足但必須做決定時，你會採用什麼原則？",
                "了解決斷力是否同時包含風險意識與可逆性判斷。",
                "你會設定哪些條件來重新檢視決定？",
            ),
            (
                "請舉例說明你如何分派工作並確保成果，而不是只追進度。",
                "評估授權、期待管理與回饋能力。",
                "若成果不如預期，你會如何處理？",
            ),
        ],
        "adaptability": [
            (
                f"請分享「{role}」工作目標突然改變時，你如何重新規劃的一次經驗。",
                "確認適應力包含辨識優先級、溝通影響與重新承諾。",
                "你主動停止或延後了哪些工作？",
            ),
            (
                "面對不熟悉的工具或領域時，你如何在短時間內達到可交付程度？",
                "了解學習策略與驗證成果的方式。",
                "你如何知道自己已掌握到足夠程度？",
            ),
            (
                "請舉例說明你根據使用者或團隊回饋快速調整做法的經驗。",
                "評估彈性是否仍保有清楚的品質與決策標準。",
                "哪些部分你選擇不調整？為什麼？",
            ),
        ],
    }
    return common.get(
        category,
        [
            (
                f"請分享「{trait}」曾如何幫助你完成一項「{role}」相關工作的具體經驗。",
                "用工作行為與成果驗證候選人對此特質的自我描述。",
                "當時你的具體行動與可衡量結果是什麼？",
            ),
            (
                f"在「{role}」工作中，「{trait}」可能帶來什麼風險或盲點？你如何管理？",
                "了解候選人的自我覺察與調整能力。",
                "請舉一個你曾調整做法的例子。",
            ),
            (
                f"請描述他人曾針對你的「{trait}」給過什麼具體回饋。",
                "以第三方回饋交叉確認特質及其職場影響。",
                "你收到回饋後做了什麼改變？",
            ),
        ],
    )


def suggest_interview_questions(
    traits: list[str],
    job_title: str,
) -> list[TraitQuestionSuggestion]:
    return [
        TraitQuestionSuggestion(
            trait=trait,
            questions=[
                SuggestedInterviewQuestion(
                    question=question,
                    purpose=purpose,
                    follow_up=follow_up,
                )
                for question, purpose, follow_up in _templates(
                    _category(trait), trait, job_title
                )
            ],
        )
        for trait in traits
    ]


def personalized_trait_interview_questions(
    traits: list[str],
    job_title: str,
    *,
    current_title: str | None = None,
    total_years: object | None = None,
    highest_education: str | None = None,
    expected_title: str | None = None,
    candidate_skills: list[str] | None = None,
    required_skills: list[str] | None = None,
    experiences: list[dict[str, object | None]] | None = None,
) -> tuple[list[TraitQuestionSuggestion], list[str]]:
    """Ground trait questions in job-related resume facts without random variation."""

    role = _clean_context(job_title, 100) or "此職位"
    title = _clean_context(current_title, 100)
    years = _clean_context(total_years, 20)
    education = _clean_context(highest_education, 60)
    target_title = _clean_context(expected_title, 100)
    skills = [value for item in (candidate_skills or []) if (value := _clean_context(item, 60))]
    wanted = [value for item in (required_skills or []) if (value := _clean_context(item, 60))]
    latest = (experiences or [None])[0]
    latest_title = _clean_context(latest.get("title"), 100) if latest else None
    latest_company = _clean_context(latest.get("company"), 100) if latest else None
    latest_description = _clean_context(latest.get("description"), 100) if latest else None

    basis = [f"應徵職位：{role}"]
    contexts: list[tuple[str, str, str]] = []
    if latest_title:
        experience_label = f"{latest_company}／{latest_title}" if latest_company else latest_title
        detail = f"，內容提到「{latest_description}」" if latest_description else ""
        contexts.append(
            (
                f"履歷顯示你最近曾擔任「{experience_label}」{detail}。請以這段經歷回答：",
                f"最近經歷：{experience_label}",
                "請先釐清候選人在該經歷中親自負責的範圍。",
            )
        )
        basis.append(f"最近經歷：{experience_label}")
    if skills:
        contexts.append(
            (
                f"履歷列出「{skills[0]}」這項技能。請結合實際使用經驗回答：",
                f"候選人技能：{skills[0]}",
                "請追問使用情境、熟練程度及可驗證成果。",
            )
        )
        basis.append(f"候選人技能：{'、'.join(skills[:4])}")
    if title or years:
        career_label = "、".join(
            part
            for part in (
                f"目前職稱「{title}」" if title else None,
                f"約 {years} 年經驗" if years else None,
            )
            if part
        )
        contexts.append(
            (
                f"你的履歷背景是{career_label}。針對轉任「{role}」請回答：",
                f"職涯背景：{career_label}",
                "請確認哪些能力可直接轉移、哪些仍需補足。",
            )
        )
        basis.append(f"職涯背景：{career_label}")
    if target_title:
        contexts.append(
            (
                f"履歷中的期望職務是「{target_title}」。和本次「{role}」機會對照後請回答：",
                f"期望職務：{target_title}",
                "請確認候選人對目標職務與實際工作內容的理解是否一致。",
            )
        )
        basis.append(f"期望職務：{target_title}")
    elif education:
        contexts.append(
            (
                f"你的履歷列出「{education}」教育背景。請連結後續工作經驗回答：",
                f"教育背景：{education}",
                "請將學習背景連結到實際工作行為，而非只確認學歷名稱。",
            )
        )
        basis.append(f"教育背景：{education}")

    skill_keys = {item.casefold() for item in skills}
    missing_skill = next((item for item in wanted if item.casefold() not in skill_keys), None)
    if missing_skill:
        contexts.append(
            (
                f"「{role}」職缺需要「{missing_skill}」，現有履歷尚未明確列出。請據實回答：",
                f"履歷與職缺差距：{missing_skill}",
                "請確認是否有未寫入履歷的經驗；若沒有，再追問具體補足計畫。",
            )
        )
        basis.append(f"待確認職缺技能：{missing_skill}")

    fallback_contexts = [
        (
            f"針對你應徵的「{role}」，請用履歷中最相關的一段經驗回答：",
            f"應徵職位：{role}",
            "請追問履歷中的具體案例、個人責任及成果證據。",
        ),
        (
            f"如果把你履歷中的經驗帶到「{role}」工作情境，請回答：",
            f"履歷經驗 × 應徵職位：{role}",
            "請確認回答和履歷內容一致，並補充尚未記載的細節。",
        ),
        (
            f"從你目前提供的職務背景出發，面對「{role}」的工作要求請回答：",
            f"現有履歷資料 × 應徵職位：{role}",
            "若履歷資訊不足，請先請候選人補充背景再評估。",
        ),
    ]
    for context in fallback_contexts:
        if len(contexts) >= 3:
            break
        contexts.append(context)
    if len(basis) == 1:
        basis.append("履歷職務背景資料較少：面試時請先補充確認")

    result: list[TraitQuestionSuggestion] = []
    for trait_index, suggestion in enumerate(suggest_interview_questions(traits, role)):
        questions: list[SuggestedInterviewQuestion] = []
        for question_index, item in enumerate(suggestion.questions):
            prefix, source, resume_follow_up = contexts[
                (trait_index + question_index) % len(contexts)
            ]
            questions.append(
                SuggestedInterviewQuestion(
                    question=f"{prefix}{item.question}",
                    purpose=item.purpose,
                    follow_up=f"{item.follow_up} {resume_follow_up}",
                    source=source,
                )
            )
        result.append(TraitQuestionSuggestion(trait=suggestion.trait, questions=questions))
    return result, basis
