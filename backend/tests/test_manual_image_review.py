from fastapi.testclient import TestClient
from app.models.commerce import AuditEvent
from sqlalchemy import select

from tests.test_projects_and_generation import (
    _prepare_candidate,
)


def _candidate_ready(
    client: TestClient,
) -> tuple[dict[str, str], str, int]:
    actual_headers, _project_id, workflow_id, current = _prepare_candidate(client)
    return actual_headers, workflow_id, int(current["revision"])


def test_manual_review_persists_checks_and_high_risk_blocks_confirmation(
    client: TestClient,
) -> None:
    headers, workflow_id, revision = _candidate_ready(client)
    reviewed = client.post(
        f"/api/v1/image-workflows/{workflow_id}/manual-review",
        headers=headers,
        json={
            "expected_revision": revision,
            "product_facts_match": True,
            "geometry_and_count_match": True,
            "logo_text_and_personalization_match": True,
            "thumbnail_readable": True,
            "compliance_risk": "high",
            "notes": "发现高风险医疗功效文字，必须阻断并重新生成。",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["status"] == "compliance_blocked"
    assert body["compliance_status"] == "high_open"
    assert body["qa_report"]["mode"] == "operator_manual_review"
    denied = client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": body["revision"]},
    )
    assert denied.status_code == 409


def test_manual_review_clear_can_reach_operator_confirmation(
    client: TestClient,
) -> None:
    headers, workflow_id, revision = _candidate_ready(client)
    reviewed = client.post(
        f"/api/v1/image-workflows/{workflow_id}/manual-review",
        headers=headers,
        json={
            "expected_revision": revision,
            "product_facts_match": True,
            "geometry_and_count_match": True,
            "logo_text_and_personalization_match": True,
            "thumbnail_readable": True,
            "compliance_risk": "clear",
            "notes": "已逐项核对商品事实、结构、数量、标识和缩略图表现。",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    confirmed = client.post(
        f"/api/v1/image-workflows/{workflow_id}/confirm",
        headers=headers,
        json={"expected_revision": reviewed.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "operator_confirmed"
    with client.app.state.database.session_factory() as db:
        actions = set(db.scalars(select(AuditEvent.action)).all())
    assert "image_workflow.manual_review_submitted" in actions
