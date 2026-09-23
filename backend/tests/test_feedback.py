"""报告反馈：upsert / 回显 / 列表聚合 / 入参校验（architecture.md §2.3 v0.14、§5.1）。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.api.feedback import FeedbackInvalid, parse_feedback
from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import ReportFeedback
from app.main import app
from tests.test_tasks_api import create_report_fixture

FEEDBACK_KEYS = {"report_id", "verdict", "comment", "updated_at"}
LIST_ITEM_KEYS = {"id", "report_id", "report_title", "verdict", "comment", "updated_at"}
AGED = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def feedback_url(report_id: str) -> str:
    return f"/api/v1/reports/{report_id}/feedback"


def stored_feedbacks() -> list[ReportFeedback]:
    with SessionLocal(bind=get_engine()) as session:
        return list(
            session.scalars(select(ReportFeedback).order_by(ReportFeedback.report_id)).all()
        )


def set_feedback_times(report_id: str, *, created_at: datetime, updated_at: datetime) -> None:
    with SessionLocal(bind=get_engine()) as session:
        feedback = session.scalars(
            select(ReportFeedback).where(ReportFeedback.report_id == report_id)
        ).one()
        feedback.created_at = created_at
        feedback.updated_at = updated_at
        session.commit()


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def parse_utc_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, value
    assert parsed.utcoffset() == timedelta(0), value
    return parsed


# ------------------------------------------------------------------ upsert 与回显
def test_submit_feedback_creates_one_local_vote_with_contract_shape(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "vote")

    with TestClient(app) as client:
        response = client.post(
            feedback_url(report_id),
            json={"verdict": "useful", "comment": "  摘要准确，徐汇店异常很关键  "},
        )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == FEEDBACK_KEYS
    assert payload["report_id"] == report_id
    assert payload["verdict"] == "useful"
    assert payload["comment"] == "摘要准确，徐汇店异常很关键"
    parse_utc_iso(payload["updated_at"])

    [stored] = stored_feedbacks()
    assert stored.report_id == report_id
    assert stored.voter == "local"
    assert stored.verdict == "useful"
    assert stored.comment == "摘要准确，徐汇店异常很关键"
    assert stored.created_at is not None


def test_resubmitting_changes_vote_in_place_and_refreshes_updated_at(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "change")

    with TestClient(app) as client:
        first = client.post(feedback_url(report_id), json={"verdict": "useful", "comment": "有用"})
        [original] = stored_feedbacks()
        set_feedback_times(report_id, created_at=AGED, updated_at=AGED)
        second = client.post(
            feedback_url(report_id),
            json={"verdict": "not_useful", "comment": "门店口径不对"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["verdict"] == "not_useful"
    assert second.json()["comment"] == "门店口径不对"
    assert parse_utc_iso(second.json()["updated_at"]) > AGED

    [stored] = stored_feedbacks()
    assert stored.id == original.id
    assert stored.verdict == "not_useful"
    assert stored.comment == "门店口径不对"
    assert as_utc(stored.created_at) == AGED
    assert as_utc(stored.updated_at) > AGED


def test_identical_resubmission_still_refreshes_updated_at(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "same")

    with TestClient(app) as client:
        client.post(feedback_url(report_id), json={"verdict": "useful", "comment": "同一句"})
        set_feedback_times(report_id, created_at=AGED, updated_at=AGED)
        response = client.post(
            feedback_url(report_id),
            json={"verdict": "useful", "comment": "同一句"},
        )

    assert response.status_code == 200
    assert parse_utc_iso(response.json()["updated_at"]) > AGED
    [stored] = stored_feedbacks()
    assert as_utc(stored.created_at) == AGED
    assert as_utc(stored.updated_at) > AGED


def test_get_feedback_echoes_null_before_voting_then_saved_vote(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "echo")

    with TestClient(app) as client:
        before = client.get(feedback_url(report_id))
        submitted = client.post(
            feedback_url(report_id),
            json={"verdict": "not_useful", "comment": "缺少渠道拆分"},
        )
        after = client.get(feedback_url(report_id))

    assert before.status_code == 200
    assert before.json() == {"feedback": None}
    assert after.status_code == 200
    assert after.json() == {"feedback": submitted.json()}


def test_absent_or_null_comment_is_stored_as_empty_string(tmp_path: Path):
    first_id, _ = create_report_fixture(tmp_path, "absent")
    second_id, _ = create_report_fixture(tmp_path, "null")

    with TestClient(app) as client:
        absent = client.post(feedback_url(first_id), json={"verdict": "useful"})
        null = client.post(feedback_url(second_id), json={"verdict": "useful", "comment": None})

    assert absent.status_code == 200
    assert null.status_code == 200
    assert absent.json()["comment"] == ""
    assert null.json()["comment"] == ""


def test_voter_in_body_is_ignored_and_never_returned(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "voter")

    with TestClient(app) as client:
        first = client.post(feedback_url(report_id), json={"verdict": "useful", "voter": "alice"})
        second = client.post(
            feedback_url(report_id),
            json={"verdict": "not_useful", "voter": "bob"},
        )
        listed = client.get("/api/v1/feedback")

    assert first.status_code == 200
    assert second.status_code == 200
    assert "voter" not in first.json()
    assert "voter" not in second.json()
    assert "voter" not in listed.json()["items"][0]
    [stored] = stored_feedbacks()
    assert stored.voter == "local"
    assert stored.verdict == "not_useful"


def test_concurrent_duplicate_submissions_converge_to_one_row(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "race")

    with TestClient(app) as client:

        def submit(index: int) -> int:
            verdict = "useful" if index % 2 else "not_useful"
            return client.post(
                feedback_url(report_id),
                json={"verdict": verdict, "comment": f"第 {index} 次"},
            ).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            statuses = list(pool.map(submit, range(24)))

    assert statuses == [200] * 24
    assert len(stored_feedbacks()) == 1


# ------------------------------------------------------------------ 入参校验与 404
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"verdict": "maybe"},
        {"verdict": "USEFUL"},
        {"verdict": None},
        {"verdict": 1},
        {"verdict": ["useful"]},
        {"verdict": "useful", "comment": 123},
        {"verdict": "useful", "comment": ["补充"]},
        {"verdict": "useful", "comment": "字" * 501},
        ["useful"],
        "useful",
    ],
    ids=[
        "missing-verdict",
        "unknown-verdict",
        "wrong-case-verdict",
        "null-verdict",
        "numeric-verdict",
        "list-verdict",
        "numeric-comment",
        "list-comment",
        "comment-501-chars",
        "array-body",
        "string-body",
    ],
)
def test_invalid_feedback_is_rejected_without_writing(tmp_path: Path, payload: object):
    report_id, _ = create_report_fixture(tmp_path, "invalid")

    with TestClient(app) as client:
        response = client.post(feedback_url(report_id), json=payload)

    assert response.status_code == 400
    assert response.json()["code"] == "FEEDBACK_INVALID"
    assert response.json()["message"]
    assert stored_feedbacks() == []


@pytest.mark.parametrize(
    "request_kwargs",
    [{}, {"content": b"null", "headers": {"content-type": "application/json"}}],
    ids=["missing-body", "json-null-body"],
)
def test_missing_or_null_body_is_feedback_invalid(tmp_path: Path, request_kwargs: dict):
    report_id, _ = create_report_fixture(tmp_path, "empty-body")

    with TestClient(app) as client:
        response = client.post(feedback_url(report_id), **request_kwargs)

    assert response.status_code == 400
    assert response.json()["code"] == "FEEDBACK_INVALID"
    assert stored_feedbacks() == []


def test_lone_surrogate_comment_is_rejected_at_the_boundary_not_500(tmp_path: Path):
    """v0.15 起由请求体边界校验先行拦截，错误码从 FEEDBACK_INVALID 变为 REQUEST_BODY_INVALID；
    「不落库、不回 500」这两条实质约定不变。"""
    report_id, _ = create_report_fixture(tmp_path, "surrogate")

    with TestClient(app) as client:
        response = client.post(
            feedback_url(report_id),
            content=b'{"verdict": "useful", "comment": "\\ud800"}',
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "REQUEST_BODY_INVALID"
    assert stored_feedbacks() == []


def test_parse_feedback_still_rejects_unencodable_comment_directly():
    """纵深防御：parse_feedback 作为纯函数仍自证，不依赖上游边界校验。"""
    with pytest.raises(FeedbackInvalid):
        parse_feedback({"verdict": "useful", "comment": "\ud800"})
    parsed = parse_feedback({"verdict": "useful", "comment": "  正常反馈  "})
    assert parsed == ("useful", "正常反馈")


def test_invalid_body_is_rejected_before_report_lookup():
    with TestClient(app) as client:
        response = client.post(feedback_url("missing-report"), json={"verdict": "maybe"})

    assert response.status_code == 400
    assert response.json()["code"] == "FEEDBACK_INVALID"


def test_changing_vote_without_comment_replaces_stored_comment(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "replace")

    with TestClient(app) as client:
        client.post(feedback_url(report_id), json={"verdict": "useful", "comment": "保留这句"})
        changed = client.post(feedback_url(report_id), json={"verdict": "not_useful"})

    assert changed.json()["comment"] == ""
    [stored] = stored_feedbacks()
    assert (stored.verdict, stored.comment) == ("not_useful", "")


def test_malformed_json_keeps_framework_422_without_writing(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "malformed")

    with TestClient(app) as client:
        response = client.post(
            feedback_url(report_id),
            content=b"{bad",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    assert stored_feedbacks() == []


def test_overlong_comment_message_is_business_wording(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "long")

    with TestClient(app) as client:
        response = client.post(
            feedback_url(report_id),
            json={"verdict": "useful", "comment": "长" * 501},
        )

    assert response.status_code == 400
    assert response.json() == {
        "code": "FEEDBACK_INVALID",
        "message": "反馈内容过长（最多 500 字）。",
    }


@pytest.mark.parametrize(
    ("comment", "status_code"),
    [
        ("a" * 500, 200),
        ("好" * 500, 200),
        ("  " + "好" * 499 + "😀" + "\n ", 200),
        ("好" * 500 + "😀", 400),
    ],
    ids=["500-ascii", "500-cjk", "trimmed-emoji-counts-one", "501-with-emoji"],
)
def test_comment_limit_counts_unicode_characters_after_trimming(
    tmp_path: Path,
    comment: str,
    status_code: int,
):
    report_id, _ = create_report_fixture(tmp_path, "limit")

    with TestClient(app) as client:
        response = client.post(
            feedback_url(report_id),
            json={"verdict": "useful", "comment": comment},
        )

    assert response.status_code == status_code
    if status_code == 200:
        assert response.json()["comment"] == comment.strip()


def test_invalid_submission_keeps_existing_vote_unchanged(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "keep")

    with TestClient(app) as client:
        saved = client.post(feedback_url(report_id), json={"verdict": "useful", "comment": "ok"})
        rejected = client.post(feedback_url(report_id), json={"verdict": "meh"})
        echoed = client.get(feedback_url(report_id))

    assert rejected.status_code == 400
    assert echoed.json() == {"feedback": saved.json()}


def test_feedback_endpoints_return_report_not_found_for_unknown_report():
    with TestClient(app) as client:
        submitted = client.post(feedback_url("missing-report"), json={"verdict": "useful"})
        echoed = client.get(feedback_url("missing-report"))

    assert submitted.status_code == 404
    assert submitted.json()["code"] == "REPORT_NOT_FOUND"
    assert echoed.status_code == 404
    assert echoed.json()["code"] == "REPORT_NOT_FOUND"
    assert stored_feedbacks() == []


# ------------------------------------------------------------------ 列表与聚合
def test_feedback_list_is_empty_with_zero_aggregate():
    with TestClient(app) as client:
        response = client.get("/api/v1/feedback")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "limit": 20,
        "offset": 0,
        "aggregate": {"useful_count": 0, "not_useful_count": 0},
    }


def test_feedback_list_orders_by_updated_at_and_aggregates_after_vote_change(
    tmp_path: Path,
):
    report_a, _ = create_report_fixture(tmp_path, "a", task_title="周报 A")
    report_b, _ = create_report_fixture(tmp_path, "b", task_title="周报 B")
    report_c, _ = create_report_fixture(tmp_path, "c", task_title="周报 C")

    with TestClient(app) as client:
        client.post(feedback_url(report_a), json={"verdict": "useful"})
        client.post(feedback_url(report_b), json={"verdict": "not_useful", "comment": "太笼统"})
        client.post(feedback_url(report_c), json={"verdict": "useful", "comment": "可执行"})
        before_change = client.get("/api/v1/feedback").json()
        client.post(feedback_url(report_a), json={"verdict": "not_useful", "comment": "改票"})
        set_feedback_times(report_a, created_at=AGED, updated_at=datetime(2026, 9, 3, tzinfo=UTC))
        set_feedback_times(report_b, created_at=AGED, updated_at=datetime(2026, 9, 1, tzinfo=UTC))
        set_feedback_times(report_c, created_at=AGED, updated_at=datetime(2026, 9, 2, tzinfo=UTC))
        response = client.get("/api/v1/feedback")

    assert before_change["aggregate"] == {"useful_count": 2, "not_useful_count": 1}
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 3
    assert payload["aggregate"] == {"useful_count": 1, "not_useful_count": 2}
    assert [item["report_id"] for item in payload["items"]] == [report_a, report_c, report_b]
    first = payload["items"][0]
    assert set(first) == LIST_ITEM_KEYS
    assert first["report_title"] == "周报 A"
    assert first["verdict"] == "not_useful"
    assert first["comment"] == "改票"
    assert parse_utc_iso(first["updated_at"]) == datetime(2026, 9, 3, tzinfo=UTC)
    assert str(tmp_path) not in response.text


def test_feedback_list_breaks_updated_at_ties_by_id_desc(tmp_path: Path):
    first_id, _ = create_report_fixture(tmp_path, "tie-1")
    second_id, _ = create_report_fixture(tmp_path, "tie-2")
    same_moment = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)

    with TestClient(app) as client:
        client.post(feedback_url(first_id), json={"verdict": "useful"})
        client.post(feedback_url(second_id), json={"verdict": "useful"})
        for report_id in (first_id, second_id):
            set_feedback_times(report_id, created_at=AGED, updated_at=same_moment)
        items = client.get("/api/v1/feedback").json()["items"]

    feedback_ids = [item["id"] for item in items]
    assert feedback_ids == sorted(feedback_ids, reverse=True)


def test_feedback_list_paginates_while_aggregate_covers_all_rows(tmp_path: Path):
    report_ids = [create_report_fixture(tmp_path, f"page-{index}")[0] for index in range(3)]

    with TestClient(app) as client:
        for index, report_id in enumerate(report_ids):
            verdict = "useful" if index < 2 else "not_useful"
            client.post(feedback_url(report_id), json={"verdict": verdict})
        first_page = client.get("/api/v1/feedback?limit=2&offset=0").json()
        second_page = client.get("/api/v1/feedback?limit=2&offset=2").json()
        capped = client.get("/api/v1/feedback?limit=500").json()

    assert len(first_page["items"]) == 2
    assert len(second_page["items"]) == 1
    assert {item["report_id"] for item in first_page["items"] + second_page["items"]} == set(
        report_ids
    )
    for page in (first_page, second_page):
        assert page["total"] == 3
        assert page["aggregate"] == {"useful_count": 2, "not_useful_count": 1}
    assert (first_page["limit"], first_page["offset"]) == (2, 0)
    assert (second_page["limit"], second_page["offset"]) == (2, 2)
    assert capped["limit"] == 50


# ------------------------------------------------------------------ 存储约束与旧库
def test_report_feedbacks_unique_key_is_report_and_voter(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "constraint")
    engine = get_engine()

    unique_constraints = inspect(engine).get_unique_constraints("report_feedbacks")
    assert {
        "name": "uq_report_feedbacks_report_id_voter",
        "column_names": ["report_id", "voter"],
    } in [
        {"name": constraint["name"], "column_names": constraint["column_names"]}
        for constraint in unique_constraints
    ]

    with SessionLocal(bind=engine) as session:
        session.add(ReportFeedback(report_id=report_id, voter="local", verdict="useful"))
        session.add(ReportFeedback(report_id=report_id, voter="m2-consumer", verdict="useful"))
        session.commit()

    with SessionLocal(bind=engine) as session:
        session.add(ReportFeedback(report_id=report_id, voter="local", verdict="not_useful"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_legacy_p1_database_gains_report_feedbacks_table(tmp_path: Path, monkeypatch):
    from tests.test_persistence import create_p1_era_database

    database_url = f"sqlite:///{tmp_path / 'p1-legacy.db'}"
    create_p1_era_database(database_url)
    monkeypatch.setenv("APP_DB_URL", database_url)

    with TestClient(app) as client:
        submitted = client.post(
            feedback_url("p1-report"),
            json={"verdict": "useful", "comment": "旧报告也能反馈"},
        )
        listed = client.get("/api/v1/feedback").json()
        report = client.get("/api/v1/reports/p1-report")

    assert "report_feedbacks" in inspect(get_engine()).get_table_names()
    assert submitted.status_code == 200
    assert listed["items"][0]["report_title"] == "legacy report"
    assert listed["aggregate"] == {"useful_count": 1, "not_useful_count": 0}
    assert report.status_code == 200
    assert report.json()["task_id"] is None

    init_db()
    assert len(stored_feedbacks()) == 1
