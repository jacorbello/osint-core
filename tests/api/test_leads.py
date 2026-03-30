"""Tests for leads API routes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi.responses import JSONResponse

from osint_core.api.routes.leads import get_lead, list_leads, update_lead
from osint_core.models.lead import LeadStatusEnum
from osint_core.schemas.lead import LeadListResponse, LeadUpdateRequest
from tests.helpers import make_request, make_user, run_async


def _compiled_sql(stmt) -> str:
    """Compile a SQLAlchemy statement to a SQL string for assertion."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _make_lead(
    *,
    lead_id: uuid.UUID | None = None,
    status: str = LeadStatusEnum.new,
    jurisdiction: str | None = "California",
    lead_type: str = "incident",
    first_surfaced_at: datetime | None = None,
) -> MagicMock:
    """Return a mock Lead ORM object with Pydantic-compatible field values."""
    lead = MagicMock()
    lead.id = lead_id or uuid.uuid4()
    lead.lead_type = lead_type
    lead.status = status
    lead.title = "Test Lead"
    lead.summary = "A test summary"
    lead.constitutional_basis = ["1A"]
    lead.jurisdiction = jurisdiction
    lead.institution = None
    lead.severity = "medium"
    lead.confidence = 0.85
    lead.dedupe_fingerprint = f"fp-{lead.id}"
    lead.plan_id = None
    lead.event_ids = []
    lead.entity_ids = []
    lead.citations = None
    lead.report_id = None
    lead.first_surfaced_at = first_surfaced_at or datetime(2026, 3, 1, tzinfo=UTC)
    lead.last_updated_at = datetime(2026, 3, 1, tzinfo=UTC)
    lead.reported_at = None
    lead.created_at = datetime(2026, 3, 1, tzinfo=UTC)
    return lead


def _make_list_db(leads: list[MagicMock], total: int | None = None) -> AsyncMock:
    """Return an AsyncSession mock for list_leads (two execute calls)."""
    db = AsyncMock()

    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = leads

    count_result = MagicMock()
    count_result.scalar_one.return_value = total if total is not None else len(leads)

    db.execute = AsyncMock(side_effect=[items_result, count_result])
    return db


def _make_single_db(lead: MagicMock | None) -> AsyncMock:
    """Return an AsyncSession mock for get_lead / update_lead (one execute)."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = lead
    db.execute = AsyncMock(return_value=result)
    return db


# ---------------------------------------------------------------------------
# GET /api/v1/leads -- list
# ---------------------------------------------------------------------------


def test_list_leads_returns_items():
    """Returns leads with page metadata."""
    lead = _make_lead()
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, LeadListResponse)
    assert len(result.items) == 1
    assert result.page.total == 1
    assert result.page.has_more is False


def test_list_leads_empty():
    """Returns empty list when no leads exist."""
    db = _make_list_db([], total=0)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, LeadListResponse)
    assert result.items == []
    assert result.page.total == 0


def test_list_leads_with_status_filter():
    """Filters by status when provided."""
    lead = _make_lead(status=LeadStatusEnum.reviewing)
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status="reviewing",
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    assert db.execute.call_count == 2
    # Verify both item and count queries include the status WHERE clause
    items_stmt = db.execute.call_args_list[0][0][0]
    count_stmt = db.execute.call_args_list[1][0][0]
    items_sql = _compiled_sql(items_stmt)
    count_sql = _compiled_sql(count_stmt)
    assert "status" in items_sql
    assert "status" in count_sql


def test_list_leads_with_jurisdiction_filter():
    """Filters by jurisdiction when provided."""
    lead = _make_lead(jurisdiction="Texas")
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction="Texas",
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    items_sql = _compiled_sql(db.execute.call_args_list[0][0][0])
    count_sql = _compiled_sql(db.execute.call_args_list[1][0][0])
    assert "jurisdiction" in items_sql
    assert "jurisdiction" in count_sql


def test_list_leads_with_lead_type_filter():
    """Filters by lead_type when provided."""
    lead = _make_lead(lead_type="policy")
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type="policy",
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    items_sql = _compiled_sql(db.execute.call_args_list[0][0][0])
    count_sql = _compiled_sql(db.execute.call_args_list[1][0][0])
    assert "lead_type" in items_sql
    assert "lead_type" in count_sql


def test_list_leads_with_date_filters():
    """Filters by date_from and date_to when provided."""
    lead = _make_lead(first_surfaced_at=datetime(2026, 2, 15, tzinfo=UTC))
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=datetime(2026, 2, 1, tzinfo=UTC),
            date_to=datetime(2026, 3, 1, tzinfo=UTC),
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    items_sql = _compiled_sql(db.execute.call_args_list[0][0][0])
    count_sql = _compiled_sql(db.execute.call_args_list[1][0][0])
    assert "first_surfaced_at" in items_sql
    assert "first_surfaced_at" in count_sql


def test_list_leads_with_all_filters():
    """All filters can be combined."""
    lead = _make_lead(
        status=LeadStatusEnum.qualified,
        jurisdiction="California",
        lead_type="incident",
        first_surfaced_at=datetime(2026, 2, 15, tzinfo=UTC),
    )
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=10,
            offset=0,
            status="qualified",
            jurisdiction="California",
            lead_type="incident",
            plan_id=None,
            date_from=datetime(2026, 2, 1, tzinfo=UTC),
            date_to=datetime(2026, 3, 1, tzinfo=UTC),
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    items_sql = _compiled_sql(db.execute.call_args_list[0][0][0])
    count_sql = _compiled_sql(db.execute.call_args_list[1][0][0])
    for col in ("status", "jurisdiction", "lead_type", "first_surfaced_at"):
        assert col in items_sql, f"Missing {col} filter in items query"
        assert col in count_sql, f"Missing {col} filter in count query"


def test_list_leads_pagination_has_more():
    """Page metadata indicates more results when total exceeds offset + limit."""
    leads = [_make_lead() for _ in range(10)]
    db = _make_list_db(leads, total=25)

    result = run_async(
        list_leads(
            limit=10,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert result.page.total == 25
    assert result.page.has_more is True
    assert result.page.offset == 0
    assert result.page.limit == 10


def test_list_leads_pagination_last_page():
    """Page metadata indicates no more results on last page."""
    leads = [_make_lead() for _ in range(5)]
    db = _make_list_db(leads, total=15)

    result = run_async(
        list_leads(
            limit=10,
            offset=10,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert result.page.total == 15
    assert result.page.has_more is False
    assert result.page.offset == 10


def test_list_leads_with_plan_id_filter():
    """Filters by plan_id when provided."""
    lead = _make_lead()
    lead.plan_id = "cal-prospecting"
    db = _make_list_db([lead], total=1)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id="cal-prospecting",
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 1
    items_sql = _compiled_sql(db.execute.call_args_list[0][0][0])
    count_sql = _compiled_sql(db.execute.call_args_list[1][0][0])
    assert "plan_id" in items_sql
    assert "plan_id" in count_sql


def test_list_leads_without_plan_id_returns_all():
    """Omitting plan_id returns all leads (backward compatible)."""
    leads = [_make_lead() for _ in range(3)]
    db = _make_list_db(leads, total=3)

    result = run_async(
        list_leads(
            limit=50,
            offset=0,
            status=None,
            jurisdiction=None,
            lead_type=None,
            plan_id=None,
            date_from=None,
            date_to=None,
            db=db,
            current_user=make_user(),
        )
    )

    assert len(result.items) == 3
    items_sql = _compiled_sql(db.execute.call_args_list[0][0][0])
    # plan_id appears in SELECT columns but should NOT appear in WHERE clause
    where_clause = items_sql.split("WHERE")[1] if "WHERE" in items_sql else ""
    assert "plan_id" not in where_clause


# ---------------------------------------------------------------------------
# GET /api/v1/leads/{lead_id} -- detail
# ---------------------------------------------------------------------------


def test_get_lead_found():
    """Returns the lead when it exists."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id)
    db = _make_single_db(lead)

    result = run_async(
        get_lead(
            lead_id=lead_id,
            request=make_request(f"/api/v1/leads/{lead_id}"),
            db=db,
            current_user=make_user(),
        )
    )

    assert result.id == lead_id


def test_get_lead_not_found():
    """Returns 404 problem response when lead does not exist."""
    lead_id = uuid.uuid4()
    db = _make_single_db(None)

    result = run_async(
        get_lead(
            lead_id=lead_id,
            request=make_request(f"/api/v1/leads/{lead_id}"),
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 404
    body = json.loads(result.body)
    assert body["code"] == "not_found"
    assert body["detail"] == "Lead not found"


# ---------------------------------------------------------------------------
# PATCH /api/v1/leads/{lead_id} -- update status
# ---------------------------------------------------------------------------


def test_update_lead_valid_transition_new_to_reviewing():
    """Successful transition from new to reviewing."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.new)
    db = _make_single_db(lead)

    run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.reviewing),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert lead.status == LeadStatusEnum.reviewing
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_update_lead_valid_transition_reviewing_to_qualified():
    """Successful transition from reviewing to qualified."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.reviewing)
    db = _make_single_db(lead)

    run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.qualified),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert lead.status == LeadStatusEnum.qualified
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_update_lead_valid_transition_qualified_to_contacted():
    """Successful transition from qualified to contacted."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.qualified)
    db = _make_single_db(lead)

    run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.contacted),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert lead.status == LeadStatusEnum.contacted
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_update_lead_valid_transition_contacted_to_retained():
    """Successful transition from contacted to retained."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.contacted)
    db = _make_single_db(lead)

    run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.retained),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert lead.status == LeadStatusEnum.retained
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_update_lead_valid_transition_new_to_declined():
    """Successful transition from new to declined."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.new)
    db = _make_single_db(lead)

    run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.declined),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert lead.status == LeadStatusEnum.declined
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_update_lead_valid_transition_stale_to_reviewing():
    """Stale leads can be re-opened to reviewing."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.stale)
    db = _make_single_db(lead)

    run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.reviewing),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert lead.status == LeadStatusEnum.reviewing
    db.commit.assert_awaited_once()
    db.refresh.assert_awaited_once()


def test_update_lead_invalid_transition_retained_to_new():
    """Retained is terminal -- cannot transition back to new."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.retained)
    db = _make_single_db(lead)

    result = run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.new),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422
    body = json.loads(result.body)
    assert body["code"] == "invalid_status_transition"
    assert "retained" in body["detail"]
    assert "new" in body["detail"]
    db.commit.assert_not_awaited()


def test_update_lead_invalid_transition_declined_to_qualified():
    """Declined is terminal -- cannot transition to qualified."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.declined)
    db = _make_single_db(lead)

    result = run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.qualified),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422
    body = json.loads(result.body)
    assert body["code"] == "invalid_status_transition"
    assert "declined" in body["detail"]
    assert "qualified" in body["detail"]


def test_update_lead_invalid_transition_new_to_contacted():
    """Cannot skip stages -- new cannot go directly to contacted."""
    lead_id = uuid.uuid4()
    lead = _make_lead(lead_id=lead_id, status=LeadStatusEnum.new)
    db = _make_single_db(lead)

    result = run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.contacted),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 422
    body = json.loads(result.body)
    assert body["code"] == "invalid_status_transition"
    assert "new" in body["detail"]
    assert "contacted" in body["detail"]


def test_update_lead_not_found():
    """Returns 404 when lead does not exist."""
    lead_id = uuid.uuid4()
    db = _make_single_db(None)

    result = run_async(
        update_lead(
            lead_id=lead_id,
            body=LeadUpdateRequest(status=LeadStatusEnum.reviewing),
            request=make_request(f"/api/v1/leads/{lead_id}", method="PATCH"),
            db=db,
            current_user=make_user(),
        )
    )

    assert isinstance(result, JSONResponse)
    assert result.status_code == 404
    body = json.loads(result.body)
    assert body["code"] == "not_found"
    assert body["detail"] == "Lead not found"
