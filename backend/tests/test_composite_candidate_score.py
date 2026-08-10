"""Acceptance contract for the composite candidate score and its weighting.

Five scores already exist for a candidate on one requisition; this module pins
down the sixth -- how the per-question score is derived, how the five are
weighted together, what happens when a component is missing, and the two things
the composite must never do: move an application's status, or exist before blind
review has released the scores it is built from.
"""

# Ruff treats pytest's intentional imported-fixture export and shadowing as unused.
# ruff: noqa: F401, F811

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from test_application_interviews import _headers, application_client

from app.models import JobApplication, JobRequisition, MatchResult, User
from app.models.security import AuditLog
from app.schemas.hr import COMPOSITE_SCORE_WEIGHT_KEYS
from app.services.interview_scoring import (
    COMPOSITE_WEIGHT_KEYS,
    DEFAULT_COMPOSITE_WEIGHTS,
    question_score,
    resolve_composite_weights,
)

_WEIGHTS_FORBIDDEN_DETAIL = "僅人資可設定綜合評分權重"


def _completed(
    stage: str,
    *,
    ratings: list[int],
    not_asked: int = 0,
    overall_score: int | None = None,
    overall_rating: int | None = None,
) -> dict[str, object]:
    questions: list[dict[str, object]] = [
        {"question": f"{stage} 已詢問題目 {index + 1}", "rating": rating}
        for index, rating in enumerate(ratings)
    ]
    questions += [
        {
            "question": f"{stage} 未詢問題目 {index + 1}",
            "not_asked_reason": "面試時間不足，留待下一階段",
        }
        for index in range(not_asked)
    ]
    payload: dict[str, object] = {
        "stage": stage,
        "interviewed_at": "2030-08-20T09:30:00+08:00",
        "mode": "video",
        "status": "completed",
        "questions": questions,
        "summary": "已完成整體總評，仍由招募團隊綜合判斷。",
        "recommendation": "advance",
    }
    if overall_score is not None:
        payload["overall_score"] = overall_score
    if overall_rating is not None:
        payload["overall_rating"] = overall_rating
    return payload


def _seed_match_result(testing_session, requisition_id: int, candidate_id: int, score: str):
    with testing_session() as db:
        db.add(
            MatchResult(
                requisition_id=requisition_id,
                candidate_id=candidate_id,
                gate_passed=True,
                total_score=Decimal(score),
                score_breakdown={"highlights": []},
            )
        )
        db.commit()


def _application(client, headers: dict[str, str], application_id: int) -> dict:
    response = client.get("/api/v1/applications", headers=headers)
    assert response.status_code == 200, response.text
    match = next(item for item in response.json() if item["id"] == application_id)
    return match


def _stored_status(testing_session, application_id: int) -> str:
    with testing_session() as db:
        application = db.get(JobApplication, application_id)
        assert application is not None
        return application.status


def test_default_weights_and_normalisation_are_the_agreed_ones() -> None:
    """The split is a product decision, so changing it has to be deliberate."""

    assert DEFAULT_COMPOSITE_WEIGHTS == {
        "resume": 20.0,
        "hr_questions": 15.0,
        "hr_overall": 25.0,
        "manager_questions": 15.0,
        "manager_overall": 25.0,
    }
    # HR and the manager weigh the same in total, and each side's holistic total
    # outweighs its per-question average.
    assert DEFAULT_COMPOSITE_WEIGHTS["hr_questions"] + DEFAULT_COMPOSITE_WEIGHTS["hr_overall"] == (
        DEFAULT_COMPOSITE_WEIGHTS["manager_questions"]
        + DEFAULT_COMPOSITE_WEIGHTS["manager_overall"]
    )
    assert DEFAULT_COMPOSITE_WEIGHTS["hr_overall"] > DEFAULT_COMPOSITE_WEIGHTS["hr_questions"]
    assert COMPOSITE_WEIGHT_KEYS == COMPOSITE_SCORE_WEIGHT_KEYS

    defaults = resolve_composite_weights(None)
    assert defaults == {
        "resume": 0.20,
        "hr_questions": 0.15,
        "hr_overall": 0.25,
        "manager_questions": 0.15,
        "manager_overall": 0.25,
    }
    # Overrides are relative, so proportional configurations are the same weighting.
    tripled = {key: value * 3 for key, value in DEFAULT_COMPOSITE_WEIGHTS.items()}
    assert resolve_composite_weights(tripled) == defaults
    # A partial override keeps the defaults for every key it does not name.
    assert resolve_composite_weights({"resume": 0}) == {
        "resume": 0.0,
        "hr_questions": 0.1875,
        "hr_overall": 0.3125,
        "manager_questions": 0.1875,
        "manager_overall": 0.3125,
    }
    # Unusable configurations carry no decision at all, exactly like match_weights.
    all_zero = dict.fromkeys(COMPOSITE_WEIGHT_KEYS, 0)
    for unusable in ({}, {"resume": -5}, {"resume": "high"}, all_zero):
        assert resolve_composite_weights(unusable) == defaults
    assert sum(resolve_composite_weights({"hr_overall": 7}).values()) == pytest.approx(1.0)


def test_question_score_excludes_not_asked_and_is_null_when_nothing_is_rated() -> None:
    # (4 + 5 + 3) / (3 * 5) * 100 -- the 未詢問 question leaves the denominator alone.
    assert question_score(
        [
            {"question": "a", "rating": 4},
            {"question": "b", "rating": 5},
            {"question": "c", "rating": 3},
            {"question": "d", "not_asked_reason": "時間不足"},
        ]
    ) == 80.0
    # Same three ratings with two more skipped questions: an unasked question must
    # not drag the score down, so the number cannot move.
    assert question_score(
        [
            {"question": "a", "rating": 4},
            {"question": "b", "rating": 5},
            {"question": "c", "rating": 3},
            {"question": "d", "not_asked_reason": "時間不足"},
            {"question": "e", "not_asked_reason": "改由主管詢問"},
        ]
    ) == 80.0

    # Null, never zero: "unknown" is not "bad".
    assert question_score([{"question": "a", "not_asked_reason": "時間不足"}]) is None
    assert question_score([{"question": "a"}]) is None
    assert question_score([]) is None
    assert question_score(None) is None

    # The lowest possible rating is a real score and still 20, not null.
    assert question_score([{"question": "a", "rating": 1}]) == 20.0
    assert question_score([{"question": "a", "rating": 5}]) == 100.0
    # Out-of-range or non-integer ratings are not ratings.
    assert question_score([{"question": "a", "rating": 0}, {"question": "b", "rating": 6}]) is None

    # One decimal place, rounded half up, identical to the interview UI's display.
    def rated(*ratings: int) -> float | None:
        return question_score(
            [{"question": f"q{index}", "rating": rating} for index, rating in enumerate(ratings)]
        )

    assert rated(4, 5, 3, 4) == 80.0
    assert rated(4, 5, 3) == 80.0
    assert rated(1, 2, 3) == 40.0
    assert rated(5, 4, 4) == 86.7
    assert rated(2, 3) == 50.0
    assert rated(3, 4, 4, 5, 5, 5, 3, 2) == 77.5


def test_composite_combines_all_five_components_and_never_moves_the_status(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")
    assert _stored_status(testing_session, application_id) == "submitted"

    hr_created = client.post(
        endpoint,
        headers=hr_headers,
        json=_completed("hr", ratings=[4, 5, 3], not_asked=1, overall_score=90),
    )
    assert hr_created.status_code == 201, hr_created.text
    manager_created = client.post(
        endpoint,
        headers=manager_headers,
        json=_completed("manager", ratings=[2, 4], not_asked=1, overall_score=70),
    )
    assert manager_created.status_code == 201, manager_created.text

    body = _application(client, hr_headers, application_id)
    # 80*.20 + 80*.15 + 90*.25 + 60*.15 + 70*.25
    assert body["composite_score"] == 77.0
    breakdown = body["composite_score_breakdown"]
    assert breakdown["status"] == "computed"
    assert breakdown["composite_score"] == 77.0
    assert breakdown["missing_components"] == []
    assert breakdown["configured_weights"] is None
    assert breakdown["resolved_weights"] == {
        "resume": 0.2,
        "hr_questions": 0.15,
        "hr_overall": 0.25,
        "manager_questions": 0.15,
        "manager_overall": 0.25,
    }
    values = {key: item["value"] for key, item in breakdown["components"].items()}
    assert values == {
        "resume": 80.0,
        "hr_questions": 80.0,
        "hr_overall": 90.0,
        "manager_questions": 60.0,
        "manager_overall": 70.0,
    }
    assert all(item["included"] for item in breakdown["components"].values())
    assert all(item["excluded_reason"] is None for item in breakdown["components"].values())
    # Nothing was missing, so no weight had to move.
    assert all(
        item["applied_weight"] == item["weight"] for item in breakdown["components"].values()
    )
    assert sum(item["applied_weight"] for item in breakdown["components"].values()) == 1.0
    assert breakdown["stages"]["hr"]["rated_question_count"] == 3
    assert breakdown["stages"]["hr"]["not_asked_question_count"] == 1
    assert breakdown["stages"]["manager"]["record_id"] == manager_created.json()["id"]

    # Evaluation must never drive application state (docs/13 §4 and the blocked-risk table).
    assert body["status"] == "submitted"
    assert _stored_status(testing_session, application_id) == "submitted"
    with testing_session() as db:
        stored = db.get(JobApplication, application_id)
        assert stored is not None
        assert stored.composite_score == Decimal("77.00")


def test_missing_resume_match_renormalises_the_remaining_four_weights(
    application_client,
) -> None:
    """A manually added candidate never went through matching; drop, do not zero."""

    client, testing_session, ids = application_client
    application_id = ids["engineering_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")

    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[4, 5, 3], overall_score=90),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "engineering-manager"),
            json=_completed("manager", ratings=[2, 4], overall_score=70),
        ).status_code
        == 201
    )

    breakdown = _application(client, hr_headers, application_id)["composite_score_breakdown"]
    components = breakdown["components"]
    assert components["resume"]["value"] is None
    assert components["resume"]["included"] is False
    assert components["resume"]["excluded_reason"] == "no_match_result"
    assert components["resume"]["applied_weight"] == 0.0
    assert breakdown["missing_components"] == ["resume"]
    # .15/.25/.15/.25 rescaled over the surviving .80, so HR and the manager still
    # weigh the same as each other.
    assert {key: components[key]["applied_weight"] for key in components if key != "resume"} == {
        "hr_questions": 0.1875,
        "hr_overall": 0.3125,
        "manager_questions": 0.1875,
        "manager_overall": 0.3125,
    }
    assert sum(item["applied_weight"] for item in components.values()) == pytest.approx(1.0)
    # 80*.1875 + 90*.3125 + 60*.1875 + 70*.3125
    assert breakdown["composite_score"] == 76.25
    assert _stored_status(testing_session, application_id) == "submitted"


def test_a_stage_without_rated_questions_folds_its_weight_into_that_stage(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    # Every HR question went unasked, so HR has a total but no question score.
    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[], not_asked=3, overall_score=90),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "design-manager"),
            json=_completed("manager", ratings=[2, 4], not_asked=1, overall_score=70),
        ).status_code
        == 201
    )

    breakdown = _application(client, hr_headers, application_id)["composite_score_breakdown"]
    components = breakdown["components"]
    assert components["hr_questions"]["value"] is None
    assert components["hr_questions"]["excluded_reason"] == "no_rated_questions"
    assert components["hr_questions"]["applied_weight"] == 0.0
    # The weight stays inside the HR stage rather than leaking to the manager.
    assert components["hr_overall"]["applied_weight"] == 0.40
    assert components["resume"]["applied_weight"] == 0.20
    assert components["manager_questions"]["applied_weight"] == 0.15
    assert components["manager_overall"]["applied_weight"] == 0.25
    # 80*.20 + 90*.40 + 60*.15 + 70*.25
    assert breakdown["composite_score"] == 78.5
    assert _stored_status(testing_session, application_id) == "submitted"


def test_a_stage_without_an_overall_score_folds_its_weight_into_its_questions(
    application_client,
) -> None:
    """The mirror rule, for records that predate overall_score."""

    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[4, 5, 3], overall_rating=4),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "design-manager"),
            json=_completed("manager", ratings=[2, 4], overall_score=70),
        ).status_code
        == 201
    )

    breakdown = _application(client, hr_headers, application_id)["composite_score_breakdown"]
    components = breakdown["components"]
    assert components["hr_overall"]["value"] is None
    assert components["hr_overall"]["excluded_reason"] == "no_overall_score"
    assert components["hr_overall"]["applied_weight"] == 0.0
    assert components["hr_questions"]["applied_weight"] == 0.40
    # The 1-5 overall_rating is never rescaled into the 0-100 total the interviewer
    # did not enter.
    assert components["hr_questions"]["value"] == 80.0
    # 80*.20 + 80*.40 + 60*.15 + 70*.25
    assert breakdown["composite_score"] == 74.5
    assert _stored_status(testing_session, application_id) == "submitted"


def test_composite_is_null_until_both_stages_submit_and_leaks_nothing_meanwhile(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    # Never computed at all: breakdown null is what distinguishes this from a
    # composite that was computed and came out null.
    untouched = _application(client, hr_headers, application_id)
    assert untouched["composite_score"] is None
    assert untouched["composite_score_breakdown"] is None

    hr_created = client.post(
        endpoint,
        headers=hr_headers,
        json=_completed("hr", ratings=[4, 5, 3], not_asked=1, overall_score=90),
    )
    assert hr_created.status_code == 201, hr_created.text

    # Blind review still withholds HR's evaluation from the manager here, so the
    # composite must not exist and the breakdown must carry no component values.
    masked = client.get(f"{endpoint}/{hr_created.json()['id']}", headers=manager_headers)
    assert masked.json()["evaluation_revealed"] is False
    assert masked.json()["overall_score"] is None
    for headers in (hr_headers, manager_headers):
        pending = _application(client, headers, application_id)
        assert pending["composite_score"] is None
        breakdown = pending["composite_score_breakdown"]
        assert breakdown["status"] == "pending_stages"
        assert breakdown["pending_stages"] == ["manager"]
        assert "components" not in breakdown
        assert "composite_score" not in breakdown

    # A manager draft is not a submission, so nothing changes.
    manager_draft = _completed("manager", ratings=[2, 4], not_asked=1, overall_score=70)
    manager_draft["status"] = "in_progress"
    manager_created = client.post(endpoint, headers=manager_headers, json=manager_draft)
    assert manager_created.status_code == 201, manager_created.text
    still_pending = _application(client, manager_headers, application_id)
    assert still_pending["composite_score"] is None
    assert still_pending["composite_score_breakdown"]["status"] == "pending_stages"

    submitted = client.patch(
        f"{endpoint}/{manager_created.json()['id']}",
        headers=manager_headers,
        json={"status": "completed"},
    )
    assert submitted.status_code == 200, submitted.text
    released = _application(client, manager_headers, application_id)
    assert released["composite_score"] == 77.0
    assert released["composite_score_breakdown"]["status"] == "computed"
    assert _stored_status(testing_session, application_id) == "submitted"


def test_computed_as_null_is_distinguishable_from_never_computed(
    application_client,
) -> None:
    """Both stages submitted, but every component unknown: null, and it says so."""

    client, testing_session, ids = application_client
    application_id = ids["engineering_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")

    # No match result for this application, every question 未詢問, and only the
    # legacy 1-5 overall_rating, which is never rescaled into a 0-100 total.
    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[], not_asked=2, overall_rating=4),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "engineering-manager"),
            json=_completed("manager", ratings=[], not_asked=2, overall_rating=3),
        ).status_code
        == 201
    )

    body = _application(client, hr_headers, application_id)
    assert body["composite_score"] is None
    breakdown = body["composite_score_breakdown"]
    # Not "pending_stages": the composite really was computed, and came out null
    # because nothing could be scored. Zero would have claimed the candidate is bad.
    assert breakdown["status"] == "computed"
    assert breakdown["composite_score"] is None
    assert sorted(breakdown["missing_components"]) == sorted(COMPOSITE_WEIGHT_KEYS)
    assert all(item["applied_weight"] == 0.0 for item in breakdown["components"].values())
    assert _stored_status(testing_session, application_id) == "submitted"


def test_reopen_clears_the_composite_and_resubmission_recomputes_it(
    application_client,
) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    manager_headers = _headers(client, "design-manager")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    hr_created = client.post(
        endpoint,
        headers=hr_headers,
        json=_completed("hr", ratings=[4, 5, 3], not_asked=1, overall_score=90),
    )
    assert hr_created.status_code == 201, hr_created.text
    manager_created = client.post(
        endpoint,
        headers=manager_headers,
        json=_completed("manager", ratings=[2, 4], not_asked=1, overall_score=70),
    )
    assert manager_created.status_code == 201, manager_created.text
    assert _application(client, hr_headers, application_id)["composite_score"] == 77.0

    record_endpoint = f"{endpoint}/{manager_created.json()['id']}"
    reopened = client.post(
        record_endpoint + "/reopen",
        headers=manager_headers,
        json={"reason": "主管發現分數點選錯誤"},
    )
    assert reopened.status_code == 200, reopened.text
    # The stage no longer has a submitted record, so by the composite's own
    # invariant it goes back to pending -- and the peer's re-masked evaluation
    # cannot survive inside a stale composite.
    reopened_view = _application(client, hr_headers, application_id)
    assert reopened_view["composite_score"] is None
    assert reopened_view["composite_score_breakdown"]["status"] == "pending_stages"
    assert reopened_view["composite_score_breakdown"]["pending_stages"] == ["manager"]

    corrected = client.patch(
        record_endpoint,
        headers=manager_headers,
        json={
            "status": "completed",
            "questions": [
                {"question": "manager 已詢問題目 1", "rating": 5},
                {"question": "manager 已詢問題目 2", "rating": 5},
                {"question": "manager 未詢問題目 1", "not_asked_reason": "時間不足"},
            ],
            "overall_score": 80,
        },
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["revision_number"] == 2

    recomputed = _application(client, hr_headers, application_id)
    # 80*.20 + 80*.15 + 90*.25 + 100*.15 + 80*.25
    assert recomputed["composite_score"] == 85.5
    breakdown = recomputed["composite_score_breakdown"]
    assert breakdown["status"] == "computed"
    assert breakdown["components"]["manager_questions"]["value"] == 100.0
    assert breakdown["stages"]["manager"]["revision_number"] == 2
    assert _stored_status(testing_session, application_id) == "submitted"


def test_configured_weights_change_the_composite(application_client) -> None:
    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    # Weigh the resume out entirely and split the rest evenly between the stages'
    # overall totals.
    weights = {
        "resume": 0,
        "hr_questions": 0,
        "hr_overall": 50,
        "manager_questions": 0,
        "manager_overall": 50,
    }
    configured = client.patch(
        f"/api/v1/requisitions/{ids['design_job']}",
        headers=hr_headers,
        json={"composite_score_weights": weights},
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["composite_score_weights"] == weights
    assert configured.json()["composite_score_weights_resolved"] == {
        "resume": 0.0,
        "hr_questions": 0.0,
        "hr_overall": 0.5,
        "manager_questions": 0.0,
        "manager_overall": 0.5,
    }

    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[4, 5, 3], not_asked=1, overall_score=90),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "design-manager"),
            json=_completed("manager", ratings=[2, 4], not_asked=1, overall_score=70),
        ).status_code
        == 201
    )

    body = _application(client, hr_headers, application_id)
    # 90*.5 + 70*.5, with the resume and both question scores weighed to nothing.
    assert body["composite_score"] == 80.0
    breakdown = body["composite_score_breakdown"]
    assert breakdown["configured_weights"] == weights
    # Zero weight is a configuration choice, not a missing component: the values
    # are still present and reported.
    assert breakdown["missing_components"] == []
    assert breakdown["components"]["resume"]["value"] == 80.0
    assert breakdown["components"]["resume"]["applied_weight"] == 0.0


def test_only_hr_may_change_the_composite_weights(application_client) -> None:
    client, testing_session, ids = application_client
    requisition_endpoint = f"/api/v1/requisitions/{ids['design_job']}"
    hr_headers = _headers(client, "hr")
    weights = {"resume": 40, "hr_overall": 10}

    forbidden = client.patch(
        requisition_endpoint,
        headers=_headers(client, "admin"),
        json={"composite_score_weights": weights},
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["detail"] == _WEIGHTS_FORBIDDEN_DETAIL
    for username in ("design-manager", "engineering-manager", "it"):
        assert (
            client.patch(
                requisition_endpoint,
                headers=_headers(client, username),
                json={"composite_score_weights": weights},
            ).status_code
            == 403
        ), username
    assert client.get(requisition_endpoint, headers=hr_headers).json()[
        "composite_score_weights"
    ] is None

    # Re-sending the whole requisition must keep working for everyone: restating a
    # weighting decides nothing, whether it is spelled as null or as the same
    # numbers the defaults already use.
    current = client.get(requisition_endpoint, headers=hr_headers).json()
    for username in ("admin", "hr"):
        unchanged = client.patch(
            requisition_endpoint,
            headers=_headers(client, username),
            json={
                "headcount": 4,
                "composite_score_weights": current["composite_score_weights"],
            },
        )
        assert unchanged.status_code == 200, (username, unchanged.text)
        assert unchanged.json()["headcount"] == 4
    restated = client.patch(
        requisition_endpoint,
        headers=_headers(client, "admin"),
        json={"composite_score_weights": {"resume": 20, "hr_questions": 15,
                                          "hr_overall": 25, "manager_questions": 15,
                                          "manager_overall": 25}},
    )
    assert restated.status_code == 200, restated.text
    assert restated.json()["composite_score_weights"] is None

    switched = client.patch(
        requisition_endpoint,
        headers=hr_headers,
        json={"composite_score_weights": weights},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["composite_score_weights"] == weights

    # An explicit null resets the requisition to the defaults, and that is a change.
    reset = client.patch(
        requisition_endpoint,
        headers=hr_headers,
        json={"composite_score_weights": None},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["composite_score_weights"] is None
    assert reset.json()["composite_score_weights_resolved"]["resume"] == 0.2

    with testing_session() as db:
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(
                    AuditLog.action == "requisition.composite_score_weights.update",
                    AuditLog.resource_type == "job_requisition",
                    AuditLog.resource_id == str(ids["design_job"]),
                )
                .order_by(AuditLog.id)
            ).all()
        )
        hr_user_id = db.scalar(select(User.id).where(User.username == "hr"))
        requisition = db.get(JobRequisition, ids["design_job"])
        assert requisition is not None
        assert requisition.composite_score_weights is None
    assert len(logs) == 2
    assert {log.actor_user_id for log in logs} == {hr_user_id}
    assert logs[0].details["composite_score_weights"] == {"from": None, "to": weights}
    assert logs[1].details["composite_score_weights"] == {"from": weights, "to": None}
    assert logs[1].details["resolved_weights"]["to"]["resume"] == 0.2


def test_composite_weights_reject_unknown_keys_and_negative_values(
    application_client,
) -> None:
    client, _, ids = application_client
    requisition_endpoint = f"/api/v1/requisitions/{ids['design_job']}"
    hr_headers = _headers(client, "hr")

    for invalid in (
        {"culture_fit": 10},
        {"resume": -1},
        {"resume": "high"},
        {"hr_overall": None},
    ):
        response = client.patch(
            requisition_endpoint,
            headers=hr_headers,
            json={"composite_score_weights": invalid},
        )
        assert response.status_code == 422, (invalid, response.text)


def test_reweighting_recomputes_the_composites_already_stored(application_client) -> None:
    """A stored composite follows the weights, without waiting for a resubmission.

    A composite is only ever read against the other candidates on the same
    requisition, so leaving the stored ones on the previous split would rank one
    list on two scales. What each composite was before the change stays recoverable
    from the audit entry rather than frozen into the ranking.
    """

    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[4, 5, 3], not_asked=1, overall_score=90),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "design-manager"),
            json=_completed("manager", ratings=[2, 4], not_asked=1, overall_score=70),
        ).status_code
        == 201
    )
    # 80*.20 + 80*.15 + 90*.25 + 60*.15 + 70*.25, on the built-in split.
    assert _application(client, hr_headers, application_id)["composite_score"] == 77.0

    weights = {
        "resume": 0,
        "hr_questions": 0,
        "hr_overall": 50,
        "manager_questions": 0,
        "manager_overall": 50,
    }
    reweighted = client.patch(
        f"/api/v1/requisitions/{ids['design_job']}",
        headers=hr_headers,
        json={"composite_score_weights": weights},
    )
    assert reweighted.status_code == 200, reweighted.text

    # Nothing was resubmitted in between: the stored number moved with the setting.
    body = _application(client, hr_headers, application_id)
    assert body["composite_score"] == 80.0
    breakdown = body["composite_score_breakdown"]
    assert breakdown["configured_weights"] == weights
    assert breakdown["components"]["resume"]["applied_weight"] == 0.0
    assert breakdown["components"]["hr_overall"]["applied_weight"] == 0.5

    with testing_session() as db:
        log = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action == "requisition.composite_score_weights.update",
                AuditLog.resource_type == "job_requisition",
                AuditLog.resource_id == str(ids["design_job"]),
            )
            .order_by(AuditLog.id.desc())
        ).first()
        assert log is not None
        details = log.details
    assert {"application_id": application_id, "from": 77.0, "to": 80.0} in details[
        "recomputed_applications"
    ]


def test_restating_the_same_weights_recomputes_nothing(application_client) -> None:
    """Only a real change recomputes: re-saving an untouched form must be a no-op.

    The job form sends the weights on every HR save, so "no change" has to stay
    free of side effects -- otherwise every unrelated edit would silently rewrite
    the composites and fill the audit log with entries that decided nothing.
    """

    client, testing_session, ids = application_client
    application_id = ids["design_application"]
    endpoint = f"/api/v1/applications/{application_id}/interview-records"
    hr_headers = _headers(client, "hr")
    _seed_match_result(testing_session, ids["design_job"], ids["bob"], "80.00")

    assert (
        client.post(
            endpoint,
            headers=hr_headers,
            json=_completed("hr", ratings=[4, 5, 3], not_asked=1, overall_score=90),
        ).status_code
        == 201
    )
    assert (
        client.post(
            endpoint,
            headers=_headers(client, "design-manager"),
            json=_completed("manager", ratings=[2, 4], not_asked=1, overall_score=70),
        ).status_code
        == 201
    )

    # The built-in split as the form sends it back, then the same split scaled up:
    # resolve_composite_weights normalises both to what the requisition already uses,
    # so neither is a change.
    restatements = (
        dict(DEFAULT_COMPOSITE_WEIGHTS),
        {
            "resume": 40,
            "hr_questions": 30,
            "hr_overall": 50,
            "manager_questions": 30,
            "manager_overall": 50,
        },
    )
    for restated in restatements:
        unchanged = client.patch(
            f"/api/v1/requisitions/{ids['design_job']}",
            headers=hr_headers,
            json={"composite_score_weights": restated},
        )
        assert unchanged.status_code == 200, unchanged.text
        assert unchanged.json()["composite_score_weights"] is None

    assert _application(client, hr_headers, application_id)["composite_score"] == 77.0
    with testing_session() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.action == "requisition.composite_score_weights.update",
                    AuditLog.resource_id == str(ids["design_job"]),
                )
            )
            == 0
        )
