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

from app.models import InterviewRecord, JobApplication
from app.models.security import AuditLog

Stage = Literal["hr", "manager"]


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
