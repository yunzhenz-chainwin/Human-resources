"""Acceptance contract for structured interview scoring and blind release.

This module intentionally exercises only public API behaviour.  It lives apart
from the implementation so schema, route, migration, and UI work can evolve
without weakening the workflow contract.
"""

# Ruff treats pytest's intentional imported-fixture export and shadowing as unused.
# ruff: noqa: F401, F811

from typing import Literal

import pytest
from sqlalchemy import select
from test_application_interviews import _headers, application_client

from app.models import InterviewRecord, JobApplication, JobRequisition, User
from app.models.security import AuditLog

Stage = Literal["hr", "manager"]

# Exactly what blind review withholds from the other side. Written out so any change
# to the masking list has to be a deliberate edit here, not a silent regression.
MASKED_RECORD_FIELDS = (
    "summary",
    "recommendation",
    "overall_rating",
    "overall_score",
    "submitted_by_id",
    "submitted_by_name",
    "last_reopen_reason",
)
MASKED_QUESTION_FIELDS = ("rating", "not_asked_reason", "notes")

_BLIND_REVIEW_LOCKED_DETAIL = "已有面試提交紀錄，評分揭露規則不可變更"


def _completed_payload(
    stage: Stage,
    *,
    questions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "stage": stage,
        "interviewed_at": "2030-08-20T09:30:00+08:00",
        "duration_minutes": 50,
        "mode": "video",
        "status": "completed",
        "questions": questions
        if questions is not None
        else [
            {
                "question": "請分享一項與職務直接相關的成果。",
                "response": "候選人說明了背景、行動與結果。",
                "rating": 4,
                "notes": "證據具體。",
            }
        ],
        "summary": "具備職務所需證據，仍由招募團隊綜合判斷。",
        "recommendation": "advance",
        "overall_rating": 4,
    }


def test_completed_questions_require_rating_or_nonblank_not_asked_reason(
    application_client,
) -> None:
    client, _, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    headers = _headers(client, "hr")
    invalid_question_sets = [
        [{"question": "缺少評分與未詢問原因"}],
        [{"question": "評分過低", "rating": 0}],
        [{"question": "評分過高", "rating": 6}],
        [{"question": "空白原因", "not_asked_reason": "   "}],
        [
            {
                "question": "二擇一欄位不可同時填寫",
                "rating": 4,
                "not_asked_reason": "時間不足",
            }
        ],
    ]

    for questions in invalid_question_sets:
        response = client.post(
            endpoint,
            headers=headers,
            json=_completed_payload("hr", questions=questions),
        )
        assert response.status_code == 422, (questions, response.text)

    valid = client.post(
        endpoint,
        headers=headers,
        json=_completed_payload(
            "hr",
            questions=[
                {
                    "question": "有詢問但面試官未逐字記錄回答",
                    "response": None,
                    "rating": 1,
                },
                {
                    "question": "本次沒有詢問的備用題",
                    "not_asked_reason": "  時間不足，留待下一階段  ",
                },
            ],
        ),
    )
    assert valid.status_code == 201, valid.text
    assert valid.json()["questions"][0]["rating"] == 1
    assert valid.json()["questions"][0]["response"] is None
    assert valid.json()["questions"][1]["rating"] is None
    assert valid.json()["questions"][1]["not_asked_reason"] == "時間不足，留待下一階段"


def test_completed_requires_overall_rating_recommendation_and_nonblank_summary(
    application_client,
) -> None:
    client, _, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    headers = _headers(client, "hr")

    for missing_field in ("overall_rating", "recommendation", "summary"):
        payload = _completed_payload("hr")
        payload.pop(missing_field)
        response = client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 422, (missing_field, response.text)

    for invalid_overall in (0, 6):
        payload = _completed_payload("hr")
        payload["overall_rating"] = invalid_overall
        response = client.post(endpoint, headers=headers, json=payload)
        assert response.status_code == 422, (invalid_overall, response.text)

    blank_summary = _completed_payload("hr")
    blank_summary["summary"] = "   "
    assert client.post(endpoint, headers=headers, json=blank_summary).status_code == 422

    null_recommendation = _completed_payload("hr")
    null_recommendation["recommendation"] = None
    assert client.post(endpoint, headers=headers, json=null_recommendation).status_code == 422


def test_completed_accepts_overall_score_alone_and_enforces_its_range(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    headers = _headers(client, "hr")

    payload = _completed_payload("hr")
    payload.pop("overall_rating")
    payload["overall_score"] = 87
    created = client.post(endpoint, headers=headers, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["overall_score"] == 87
    assert created.json()["overall_rating"] is None

    for boundary in (0, 100):
        bounded = _completed_payload("hr")
        bounded.pop("overall_rating")
        bounded["overall_score"] = boundary
        response = client.post(endpoint, headers=headers, json=bounded)
        assert response.status_code == 201, (boundary, response.text)
        assert response.json()["overall_score"] == boundary

    for out_of_range in (-1, 101):
        invalid = _completed_payload("hr")
        invalid["overall_score"] = out_of_range
        response = client.post(endpoint, headers=headers, json=invalid)
        assert response.status_code == 422, (out_of_range, response.text)

    neither = _completed_payload("hr")
    neither.pop("overall_rating")
    assert client.post(endpoint, headers=headers, json=neither).status_code == 422

    with testing_session() as db:
        record = db.get(InterviewRecord, created.json()["id"])
        assert record is not None
        assert record.overall_score == 87
        assert record.overall_rating is None


def test_rating_only_record_stays_submittable_after_a_reopen(application_client) -> None:
    """A record predating overall_score must survive reopen and resubmission."""

    client, testing_session, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    headers = _headers(client, "hr")

    created = client.post(endpoint, headers=headers, json=_completed_payload("hr"))
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    assert created.json()["overall_rating"] == 4
    assert created.json()["overall_score"] is None

    record_endpoint = f"{endpoint}/{record_id}"
    reopened = client.post(
        record_endpoint + "/reopen",
        headers=headers,
        json={"reason": "補正舊制紀錄的敘述，總分欄位仍為空白"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["overall_score"] is None

    resubmitted = client.patch(
        record_endpoint,
        headers=headers,
        json={"status": "completed"},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["overall_rating"] == 4
    assert resubmitted.json()["overall_score"] is None
    assert resubmitted.json()["revision_number"] == 2

    # Clearing the only score present must still fail the completed contract.
    reopened_again = client.post(
        record_endpoint + "/reopen",
        headers=headers,
        json={"reason": "確認清空唯一分數欄位會被擋下"},
    )
    assert reopened_again.status_code == 200, reopened_again.text
    assert (
        client.patch(
            record_endpoint,
            headers=headers,
            json={"status": "completed", "overall_rating": None},
        ).status_code
        == 422
    )

    with testing_session() as db:
        record = db.get(InterviewRecord, record_id)
        assert record is not None
        assert record.overall_rating == 4
        assert record.overall_score is None


@pytest.mark.parametrize("record_status", ["planned", "in_progress", "cancelled", "no_show"])
def test_non_completed_statuses_allow_partial_scorecards(
    application_client,
    record_status: str,
) -> None:
    client, _, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    response = client.post(
        endpoint,
        headers=_headers(client, "hr"),
        json={
            "stage": "hr",
            "interviewed_at": "2030-08-20T09:30:00+08:00",
            "mode": "video",
            "status": record_status,
            "questions": [{"question": "尚未完成評分的草稿題目"}],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == record_status


def test_draft_submission_validates_the_merged_completed_record(application_client) -> None:
    client, _, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    headers = _headers(client, "hr")
    draft = client.post(
        endpoint,
        headers=headers,
        json={
            "stage": "hr",
            "interviewed_at": "2030-08-20T09:30:00+08:00",
            "mode": "video",
            "status": "in_progress",
            "questions": [{"question": "尚未評分的題目"}],
        },
    )
    assert draft.status_code == 201, draft.text
    draft_body = draft.json()
    record_endpoint = f"{endpoint}/{draft_body['id']}"
    assert draft_body["revision_number"] == 0
    assert draft_body["submitted_at"] is None
    assert draft_body["submitted_by_id"] is None
    assert draft_body["submitted_by_name"] is None
    assert draft_body["last_reopen_reason"] is None

    incomplete_submit = client.patch(
        record_endpoint,
        headers=headers,
        json={"status": "completed"},
    )
    assert incomplete_submit.status_code == 422, incomplete_submit.text

    completed = client.patch(
        record_endpoint,
        headers=headers,
        json={
            "status": "completed",
            "questions": [
                {
                    "question": "尚未評分的題目",
                    "not_asked_reason": "面試時間不足",
                }
            ],
            "summary": "已完成整體總評。",
            "recommendation": "hold",
            "overall_rating": 3,
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert completed.json()["revision_number"] == 1
    assert completed.json()["submitted_at"] is not None
    assert completed.json()["submitted_by_id"] is not None
    assert completed.json()["submitted_by_name"] == "Application HR"
    assert completed.json()["last_reopen_reason"] is None


def test_completed_record_is_locked_until_owner_reopens_it(application_client) -> None:
    client, testing_session, ids = application_client
    endpoint = f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    headers = _headers(client, "hr")
    created = client.post(endpoint, headers=headers, json=_completed_payload("hr"))
    assert created.status_code == 201, created.text
    created_body = created.json()
    record_id = created_body["id"]
    record_endpoint = f"{endpoint}/{record_id}"
    assert created_body["revision_number"] == 1
    assert created_body["submitted_at"] is not None
    assert created_body["submitted_by_id"] is not None
    assert created_body["submitted_by_name"] == "Application HR"
    assert created_body["last_reopen_reason"] is None

    locked_edit = client.patch(
        record_endpoint,
        headers=headers,
        json={"summary": "不可直接改寫已提交內容。"},
    )
    assert locked_edit.status_code == 409, locked_edit.text
    assert (
        client.patch(
            record_endpoint,
            headers=headers,
            json={"status": "in_progress"},
        ).status_code
        == 409
    )

    assert client.post(f"{record_endpoint}/reopen", headers=headers).status_code == 422
    assert (
        client.post(
            f"{record_endpoint}/reopen",
            headers=headers,
            json={},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"{record_endpoint}/reopen",
            headers=headers,
            json={"reason": "   "},
        ).status_code
        == 422
    )

    reopened = client.post(
        f"{record_endpoint}/reopen",
        headers=headers,
        json={"reason": "  補正面試官誤選的分數  "},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["status"] == "in_progress"
    assert reopened.json()["questions"] == created_body["questions"]
    assert reopened.json()["summary"] == created_body["summary"]
    assert reopened.json()["revision_number"] == 1
    assert reopened.json()["submitted_at"] == created_body["submitted_at"]
    assert reopened.json()["submitted_by_id"] == created_body["submitted_by_id"]
    assert reopened.json()["submitted_by_name"] == created_body["submitted_by_name"]
    assert reopened.json()["last_reopen_reason"] == "補正面試官誤選的分數"
    assert (
        client.post(
            f"{record_endpoint}/reopen",
            headers=headers,
            json={"reason": "不得重複重開"},
        ).status_code
        == 409
    )

    edited = client.patch(
        record_endpoint,
        headers=headers,
        json={"summary": "重開後可修正，重新完成前仍屬草稿。"},
    )
    assert edited.status_code == 200, edited.text

    resubmitted = client.patch(
        record_endpoint,
        headers=headers,
        json={"status": "completed"},
    )
    assert resubmitted.status_code == 200, resubmitted.text
    assert resubmitted.json()["revision_number"] == 2
    assert resubmitted.json()["submitted_at"] is not None
    assert resubmitted.json()["submitted_by_id"] == created_body["submitted_by_id"]
    assert resubmitted.json()["submitted_by_name"] == "Application HR"
    assert resubmitted.json()["last_reopen_reason"] == "補正面試官誤選的分數"

    with testing_session() as db:
        actions = set(
            db.scalars(
                select(AuditLog.action).where(
                    AuditLog.resource_type == "interview_record",
                    AuditLog.resource_id == str(record_id),
                )
            ).all()
        )
        assert "application.interview_record.create" in actions
        assert "application.interview_record.reopen" in actions
        assert "application.interview_record.update" in actions


def test_reopen_and_read_enforce_stage_role_and_department_scope(
    application_client,
) -> None:
    client, _, ids = application_client
    endpoint = f"/api/v1/applications/{ids['design_application']}/interview-records"
    design_headers = _headers(client, "design-manager")
    created = client.post(
        endpoint,
        headers=design_headers,
        json=_completed_payload("manager"),
    )
    assert created.status_code == 201, created.text
    record_endpoint = f"{endpoint}/{created.json()['id']}"

    assert client.get(endpoint, headers=_headers(client, "engineering-manager")).status_code == 403
    assert client.get(endpoint, headers=_headers(client, "it")).status_code == 403
    assert (
        client.post(
            record_endpoint + "/reopen",
            headers=_headers(client, "hr"),
            json={"reason": "錯誤階段"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            record_endpoint + "/reopen",
            headers=_headers(client, "engineering-manager"),
            json={"reason": "錯誤部門"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            record_endpoint + "/reopen",
            headers=_headers(client, "admin"),
            json={"reason": "管理員不是面試紀錄擁有者"},
        ).status_code
        == 403
    )

    allowed = client.post(
        record_endpoint + "/reopen",
        headers=design_headers,
        json={"reason": "主管發現評分點選錯誤"},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "in_progress"


def test_blind_release_waits_for_both_completions_and_rehides_after_reopen(
    application_client,
) -> None:
    client, _, ids = application_client
    endpoint = f"/api/v1/applications/{ids['design_application']}/interview-records"
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")
    hr_payload = _completed_payload(
        "hr",
        questions=[
            {
                "question": "請說明求職動機。",
                "response": "候選人希望擴大產品影響力。",
                "rating": 4,
                "notes": "例子明確。",
            },
            {
                "question": "備用追問題。",
                "not_asked_reason": "前題已取得足夠證據",
            },
        ],
    )
    hr_payload["private_notes"] = "HR 限閱薪資討論。"
    hr_created = client.post(endpoint, headers=hr_headers, json=hr_payload)
    assert hr_created.status_code == 201, hr_created.text

    manager_payload = _completed_payload("manager")
    manager_payload["status"] = "in_progress"
    manager_created = client.post(endpoint, headers=manager_headers, json=manager_payload)
    assert manager_created.status_code == 201, manager_created.text

    manager_sees_hr = client.get(f"{endpoint}/{hr_created.json()['id']}", headers=manager_headers)
    assert manager_sees_hr.status_code == 200
    masked_hr = manager_sees_hr.json()
    assert masked_hr["questions"][0]["response"] == "候選人希望擴大產品影響力。"
    assert masked_hr["questions"][0]["rating"] is None
    assert masked_hr["questions"][0]["notes"] is None
    assert masked_hr["questions"][1]["not_asked_reason"] is None
    assert masked_hr["summary"] is None
    assert masked_hr["recommendation"] is None
    assert masked_hr["overall_rating"] is None
    assert masked_hr["private_notes"] is None
    assert masked_hr["evaluation_revealed"] is False

    hr_sees_manager = client.get(
        f"{endpoint}/{manager_created.json()['id']}", headers=hr_headers
    ).json()
    assert hr_sees_manager["questions"][0]["rating"] is None
    assert hr_sees_manager["summary"] is None
    assert hr_sees_manager["evaluation_revealed"] is False

    manager_submitted = client.patch(
        f"{endpoint}/{manager_created.json()['id']}",
        headers=manager_headers,
        json={"status": "completed"},
    )
    assert manager_submitted.status_code == 200, manager_submitted.text

    released_hr = client.get(
        f"{endpoint}/{hr_created.json()['id']}", headers=manager_headers
    ).json()
    assert released_hr["evaluation_revealed"] is True
    assert released_hr["questions"][0]["rating"] == 4
    assert released_hr["questions"][1]["not_asked_reason"] == "前題已取得足夠證據"
    assert released_hr["summary"] == hr_payload["summary"]
    assert released_hr["private_notes"] is None

    reopened = client.post(
        f"{endpoint}/{manager_created.json()['id']}/reopen",
        headers=manager_headers,
        json={"reason": "補正主管評分證據"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["last_reopen_reason"] == "補正主管評分證據"
    assert reopened.json()["revision_number"] == 1

    rehidden_hr = client.get(
        f"{endpoint}/{hr_created.json()['id']}", headers=manager_headers
    ).json()
    rehidden_manager = client.get(
        f"{endpoint}/{manager_created.json()['id']}", headers=hr_headers
    ).json()
    assert rehidden_hr["evaluation_revealed"] is False
    assert rehidden_hr["questions"][0]["rating"] is None
    assert rehidden_hr["questions"][1]["not_asked_reason"] is None
    assert rehidden_manager["evaluation_revealed"] is False
    assert rehidden_manager["overall_rating"] is None
    assert rehidden_manager["submitted_by_id"] is None
    assert rehidden_manager["submitted_by_name"] is None
    assert rehidden_manager["last_reopen_reason"] is None


def test_question_plan_version_link_survives_regeneration_and_reopen(
    application_client,
) -> None:
    client, _, ids = application_client
    application_id = ids["engineering_application"]
    headers = _headers(client, "hr")
    plan_endpoint = (
        f"/api/v1/applications/{application_id}/interview-question-plan/generate?stage=hr"
    )
    first_plan_response = client.post(plan_endpoint, headers=headers)
    assert first_plan_response.status_code == 200, first_plan_response.text
    first_plan = first_plan_response.json()

    questions = [
        {
            "question": item["question"],
            "trait": item["category"],
            "purpose": item["purpose"],
            "follow_up": item["follow_up"],
            "source": item["source"],
            "rating": 4,
        }
        for item in first_plan["questions"]
    ]
    records_endpoint = f"/api/v1/applications/{application_id}/interview-records"
    payload = _completed_payload("hr", questions=questions)
    payload["question_plan_id"] = first_plan["id"]
    created = client.post(records_endpoint, headers=headers, json=payload)
    assert created.status_code == 201, created.text
    record_id = created.json()["id"]
    original_questions = created.json()["questions"]

    second_plan_response = client.post(plan_endpoint + "&force=true", headers=headers)
    assert second_plan_response.status_code == 200, second_plan_response.text
    second_plan = second_plan_response.json()
    assert second_plan["version"] == first_plan["version"] + 1
    assert second_plan["id"] != first_plan["id"]

    record_endpoint = f"{records_endpoint}/{record_id}"
    stored = client.get(record_endpoint, headers=headers)
    assert stored.status_code == 200
    assert stored.json()["question_plan_id"] == first_plan["id"]
    assert stored.json()["question_plan_version"] == first_plan["version"]
    assert stored.json()["questions"] == original_questions

    reopened = client.post(
        record_endpoint + "/reopen",
        headers=headers,
        json={"reason": "補正舊版本評分，不得換綁新版題目"},
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["question_plan_id"] == first_plan["id"]
    assert reopened.json()["question_plan_version"] == first_plan["version"]
    assert reopened.json()["questions"] == original_questions
    assert (
        client.patch(
            record_endpoint,
            headers=headers,
            json={"question_plan_id": second_plan["id"]},
        ).status_code
        == 422
    )


def test_completed_recommendation_never_changes_application_status_automatically(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    payload = _completed_payload("manager")
    payload["recommendation"] = "offer"

    created = client.post(
        endpoint,
        headers=_headers(client, "design-manager"),
        json=payload,
    )
    assert created.status_code == 201, created.text
    assert created.json()["recommendation"] == "offer"

    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        assert application.status == "submitted"
        record = db.get(InterviewRecord, created.json()["id"])
        assert record is not None
        assert record.recommendation == "offer"


def test_blind_review_defaults_to_enabled_and_keeps_todays_masking(
    application_client,
) -> None:
    """Regression guard: an untouched requisition behaves exactly as it did before."""

    client, _, ids = application_client
    hr_headers = _headers(client, "hr")
    requisition_endpoint = f"/api/v1/requisitions/{ids['design_job']}"
    before = client.get(requisition_endpoint, headers=hr_headers)
    assert before.status_code == 200, before.text
    assert before.json()["blind_review_enabled"] is True
    assert before.json()["blind_review_locked"] is False

    endpoint = f"/api/v1/applications/{ids['design_application']}/interview-records"
    hr_payload = _completed_payload("hr")
    hr_payload["overall_score"] = 82
    hr_created = client.post(endpoint, headers=hr_headers, json=hr_payload)
    assert hr_created.status_code == 201, hr_created.text

    manager_headers = _headers(client, "design-manager")
    masked = client.get(f"{endpoint}/{hr_created.json()['id']}", headers=manager_headers)
    assert masked.status_code == 200, masked.text
    assert masked.json()["evaluation_revealed"] is False
    assert masked.json()["questions"][0]["rating"] is None
    assert masked.json()["summary"] is None
    assert masked.json()["recommendation"] is None
    assert masked.json()["overall_rating"] is None
    assert masked.json()["overall_score"] is None

    listed = client.get(endpoint, headers=manager_headers)
    assert listed.status_code == 200, listed.text
    assert [item["evaluation_revealed"] for item in listed.json()] == [False]

    # A submitted interview freezes the decision from here on.
    after = client.get(requisition_endpoint, headers=hr_headers)
    assert after.json()["blind_review_enabled"] is True
    assert after.json()["blind_review_locked"] is True


def test_disabled_blind_review_reveals_the_other_side_before_submission(
    application_client,
) -> None:
    client, _, ids = application_client
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")
    switched = client.patch(
        f"/api/v1/requisitions/{ids['design_job']}",
        headers=hr_headers,
        json={"blind_review_enabled": False},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["blind_review_enabled"] is False
    assert switched.json()["blind_review_locked"] is False

    endpoint = f"/api/v1/applications/{ids['design_application']}/interview-records"
    hr_payload = _completed_payload("hr")
    hr_payload["overall_score"] = 91
    hr_payload["private_notes"] = "HR 限閱薪資討論。"
    hr_created = client.post(endpoint, headers=hr_headers, json=hr_payload)
    assert hr_created.status_code == 201, hr_created.text

    # The manager has submitted nothing at all and still reads the HR evaluation.
    manager_view = client.get(
        f"{endpoint}/{hr_created.json()['id']}", headers=manager_headers
    ).json()
    assert manager_view["evaluation_revealed"] is True
    assert manager_view["questions"][0]["rating"] == 4
    assert manager_view["questions"][0]["notes"] == "證據具體。"
    assert manager_view["summary"] == hr_payload["summary"]
    assert manager_view["recommendation"] == "advance"
    assert manager_view["overall_rating"] == 4
    assert manager_view["overall_score"] == 91
    assert manager_view["submitted_by_name"] == "Application HR"
    # HR-private notes are a separate rule and stay HR-only either way.
    assert manager_view["private_notes"] is None
    assert manager_view["private_notes_visible"] is False

    manager_draft = _completed_payload("manager")
    manager_draft["status"] = "in_progress"
    manager_created = client.post(endpoint, headers=manager_headers, json=manager_draft)
    assert manager_created.status_code == 201, manager_created.text
    hr_view = client.get(
        f"{endpoint}/{manager_created.json()['id']}", headers=hr_headers
    ).json()
    assert hr_view["evaluation_revealed"] is True
    assert hr_view["questions"][0]["rating"] == 4
    assert hr_view["summary"] == manager_draft["summary"]
    assert hr_view["recommendation"] == "advance"

    # The engineering requisition was never switched, so it still masks.
    other_endpoint = (
        f"/api/v1/applications/{ids['engineering_application']}/interview-records"
    )
    other_created = client.post(
        other_endpoint, headers=hr_headers, json=_completed_payload("hr")
    )
    assert other_created.status_code == 201, other_created.text
    other_view = client.get(
        f"{other_endpoint}/{other_created.json()['id']}",
        headers=_headers(client, "engineering-manager"),
    ).json()
    assert other_view["evaluation_revealed"] is False
    assert other_view["summary"] is None


def test_blind_review_rule_is_immutable_once_an_interview_is_submitted(
    application_client,
) -> None:
    client, _, ids = application_client
    hr_headers = _headers(client, "hr")
    endpoint = f"/api/v1/applications/{ids['design_application']}/interview-records"
    requisition_endpoint = f"/api/v1/requisitions/{ids['design_job']}"

    created = client.post(endpoint, headers=hr_headers, json=_completed_payload("hr"))
    assert created.status_code == 201, created.text
    assert client.get(requisition_endpoint, headers=hr_headers).json()[
        "blind_review_locked"
    ]

    blocked = client.patch(
        requisition_endpoint,
        headers=hr_headers,
        json={"blind_review_enabled": False},
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == _BLIND_REVIEW_LOCKED_DETAIL

    # Reopening the record must not reopen the decision, or the lock would be
    # trivially bypassable: reopen, unmask, read the other side.
    reopened = client.post(
        f"{endpoint}/{created.json()['id']}/reopen",
        headers=hr_headers,
        json={"reason": "補正評分敘述，揭露規則仍不可變更"},
    )
    assert reopened.status_code == 200, reopened.text
    assert client.get(requisition_endpoint, headers=hr_headers).json()[
        "blind_review_locked"
    ]
    still_blocked = client.patch(
        requisition_endpoint,
        headers=hr_headers,
        json={"blind_review_enabled": False},
    )
    assert still_blocked.status_code == 409, still_blocked.text
    assert still_blocked.json()["detail"] == _BLIND_REVIEW_LOCKED_DETAIL

    # Unrelated edits, and re-sending the unchanged rule, must keep working.
    unchanged = client.patch(
        requisition_endpoint,
        headers=hr_headers,
        json={"headcount": 2, "blind_review_enabled": True},
    )
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["headcount"] == 2
    assert unchanged.json()["blind_review_enabled"] is True

    # A requisition with no submitted interview is still free to change.
    engineering_endpoint = f"/api/v1/requisitions/{ids['engineering_job']}"
    free = client.patch(
        engineering_endpoint,
        headers=hr_headers,
        json={"blind_review_enabled": False},
    )
    assert free.status_code == 200, free.text
    assert free.json()["blind_review_enabled"] is False


def test_only_hr_may_change_the_blind_review_rule(application_client) -> None:
    client, testing_session, ids = application_client
    requisition_endpoint = f"/api/v1/requisitions/{ids['design_job']}"
    hr_headers = _headers(client, "hr")

    forbidden = client.patch(
        requisition_endpoint,
        headers=_headers(client, "admin"),
        json={"blind_review_enabled": False},
    )
    assert forbidden.status_code == 403, forbidden.text
    for username in ("design-manager", "engineering-manager", "it"):
        assert (
            client.patch(
                requisition_endpoint,
                headers=_headers(client, username),
                json={"blind_review_enabled": False},
            ).status_code
            == 403
        ), username
    assert client.get(requisition_endpoint, headers=hr_headers).json()[
        "blind_review_enabled"
    ]

    # An admin editing anything else, or restating the current rule, is untouched.
    admin_edit = client.patch(
        requisition_endpoint,
        headers=_headers(client, "admin"),
        json={"headcount": 3, "blind_review_enabled": True},
    )
    assert admin_edit.status_code == 200, admin_edit.text
    assert admin_edit.json()["headcount"] == 3

    switched = client.patch(
        requisition_endpoint,
        headers=hr_headers,
        json={"blind_review_enabled": False},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["blind_review_enabled"] is False

    with testing_session() as db:
        logs = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "requisition.blind_review.update",
                    AuditLog.resource_type == "job_requisition",
                    AuditLog.resource_id == str(ids["design_job"]),
                )
            ).all()
        )
        hr_user_id = db.scalar(select(User.id).where(User.username == "hr"))
    assert len(logs) == 1
    assert logs[0].actor_user_id == hr_user_id
    assert logs[0].created_at is not None
    assert logs[0].details["blind_review_enabled"] == {"from": True, "to": False}


def _new_requisition(req_no: str, department_id: int, **overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "req_no": req_no,
        "title": "新產品設計師",
        "department_id": department_id,
        "employment_type": "full_time",
        "work_city": "台北市",
        "jd": "負責設計流程與使用者研究。",
    }
    payload.update(overrides)
    return payload


def _blind_review_audits(db, requisition_id: int | None = None) -> list[AuditLog]:
    conditions = [
        AuditLog.action == "requisition.blind_review.update",
        AuditLog.resource_type == "job_requisition",
    ]
    if requisition_id is not None:
        conditions.append(AuditLog.resource_id == str(requisition_id))
    return list(db.scalars(select(AuditLog).where(*conditions)).all())


def test_hr_may_create_a_requisition_with_blind_review_already_off(
    application_client,
) -> None:
    """The rule is settable at create time, so nobody has to edit a new job to fix it."""

    client, testing_session, ids = application_client
    hr_headers = _headers(client, "hr")
    created = client.post(
        "/api/v1/requisitions",
        headers=hr_headers,
        json=_new_requisition("APP-DES-900", ids["design"], blind_review_enabled=False),
    )
    assert created.status_code == 201, created.text
    assert created.json()["blind_review_enabled"] is False
    # The PATCH lock has nothing to apply to yet: a requisition created a moment ago
    # has no applications, so it cannot carry a submitted interview.
    assert created.json()["blind_review_locked"] is False

    requisition_id = created.json()["id"]
    stored = client.get(f"/api/v1/requisitions/{requisition_id}", headers=hr_headers)
    assert stored.status_code == 200, stored.text
    assert stored.json()["blind_review_enabled"] is False
    assert stored.json()["blind_review_locked"] is False

    with testing_session() as db:
        logs = _blind_review_audits(db, requisition_id)
        hr_user_id = db.scalar(select(User.id).where(User.username == "hr"))
    assert len(logs) == 1
    assert logs[0].actor_user_id == hr_user_id
    assert logs[0].department_id == ids["design"]
    assert logs[0].created_at is not None
    assert logs[0].details["req_no"] == "APP-DES-900"
    assert logs[0].details["blind_review_enabled"] == {"from": True, "to": False}

    # Auditing the decision means the row has to be flushed before the commit, which
    # must not change how a duplicate 需求單號 reports itself.
    duplicate = client.post(
        "/api/v1/requisitions",
        headers=hr_headers,
        json=_new_requisition("APP-DES-900", ids["design"]),
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["detail"] == "需求單號重複或關聯資料不存在"


def test_only_hr_may_create_a_requisition_with_blind_review_off(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    admin_headers = _headers(client, "admin")
    forbidden = client.post(
        "/api/v1/requisitions",
        headers=admin_headers,
        json=_new_requisition("APP-DES-901", ids["design"], blind_review_enabled=False),
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["detail"] == "僅人資可設定面試評分揭露規則"
    # A refused decision leaves no half-created requisition and no audit trail.
    with testing_session() as db:
        refused = db.scalar(
            select(JobRequisition).where(JobRequisition.req_no == "APP-DES-901")
        )
        assert refused is None
        assert _blind_review_audits(db) == []

    # Restating the default is not a decision, exactly as on PATCH, so an admin whose
    # client posts the whole form keeps working.
    restated = client.post(
        "/api/v1/requisitions",
        headers=admin_headers,
        json=_new_requisition("APP-DES-902", ids["design"], blind_review_enabled=True),
    )
    assert restated.status_code == 201, restated.text
    assert restated.json()["blind_review_enabled"] is True

    # Managers never reach the rule at all: they cannot create here in the first place.
    for username in ("design-manager", "engineering-manager", "it"):
        blocked = client.post(
            "/api/v1/requisitions",
            headers=_headers(client, username),
            json=_new_requisition("APP-DES-903", ids["design"], blind_review_enabled=False),
        )
        assert blocked.status_code == 403, (username, blocked.text)


def test_a_created_requisition_stays_blind_when_the_flag_is_absent(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    hr_headers = _headers(client, "hr")
    absent = client.post(
        "/api/v1/requisitions",
        headers=hr_headers,
        json=_new_requisition("APP-DES-904", ids["design"]),
    )
    assert absent.status_code == 201, absent.text
    assert absent.json()["blind_review_enabled"] is True
    assert absent.json()["blind_review_locked"] is False

    # An explicit null decides nothing either: the column is NOT NULL, so the model
    # default has to stay in charge.
    explicit_null = client.post(
        "/api/v1/requisitions",
        headers=hr_headers,
        json=_new_requisition("APP-DES-905", ids["design"], blind_review_enabled=None),
    )
    assert explicit_null.status_code == 201, explicit_null.text
    assert explicit_null.json()["blind_review_enabled"] is True

    # Nothing decided, nothing audited. Together with the two tests above this also
    # pins the create path's idea of the default to the column default: move one
    # without the other and one of the three fails.
    with testing_session() as db:
        assert _blind_review_audits(db) == []


def test_masked_field_list_is_unchanged_while_blind_review_is_on(
    application_client,
) -> None:
    client, _, ids = application_client
    hr_headers = _headers(client, "hr")
    endpoint = f"/api/v1/applications/{ids['design_application']}/interview-records"
    payload = _completed_payload(
        "hr",
        questions=[
            {
                "question": "請說明求職動機。",
                "trait": "motivation",
                "response": "候選人希望擴大產品影響力。",
                "rating": 4,
                "notes": "例子明確。",
                "purpose": "確認動機與職務相符",
                "follow_up": "請再說明可衡量的成果",
                "source": "hr_standard",
            },
            {
                "question": "備用追問題。",
                "not_asked_reason": "前題已取得足夠證據",
            },
        ],
    )
    payload["overall_score"] = 88
    payload["private_notes"] = "HR 限閱薪資討論。"
    created = client.post(endpoint, headers=hr_headers, json=payload)
    assert created.status_code == 201, created.text
    owner_view = created.json()
    assert owner_view["evaluation_revealed"] is True

    masked = client.get(
        f"{endpoint}/{created.json()['id']}",
        headers=_headers(client, "design-manager"),
    ).json()
    assert masked["evaluation_revealed"] is False
    for field in MASKED_RECORD_FIELDS:
        assert masked[field] is None, field
    for masked_question, owner_question in zip(
        masked["questions"], owner_view["questions"], strict=True
    ):
        assert set(masked_question) == set(owner_question)
        for field, value in owner_question.items():
            if field in MASKED_QUESTION_FIELDS:
                assert masked_question[field] is None, field
            else:
                assert masked_question[field] == value, field

    # Nothing outside the documented list is withheld.
    separately_ruled = {
        "questions",
        "private_notes",
        "private_notes_visible",
        "evaluation_revealed",
    }
    for field, value in owner_view.items():
        if field in MASKED_RECORD_FIELDS or field in separately_ruled:
            continue
        assert masked[field] == value, field
    assert masked["private_notes"] is None
    assert masked["submitted_at"] == owner_view["submitted_at"]
    assert masked["revision_number"] == owner_view["revision_number"]
    assert masked["interviewer_name"] == owner_view["interviewer_name"]
