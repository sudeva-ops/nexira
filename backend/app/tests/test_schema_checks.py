"""The 35 checks from docs/schema/checks/20_checks_as_api.sql, ported to pytest.

Each test builds its own tenants and data, so the checks are independent.
Everything here runs as nexira_api.
"""

import re
import uuid
from dataclasses import dataclass

import asyncpg
import pytest

from app.tests.conftest import DbUrls, create_tenant, set_tenant

DB_ERROR = asyncpg.PostgresError


@dataclass
class Tenants:
    a: uuid.UUID
    b: uuid.UUID
    issuer_a: str


@pytest.fixture
async def tenants(db: DbUrls) -> Tenants:
    a = await create_tenant(db, "Tenant A")
    b = await create_tenant(db, "Tenant B")
    return Tenants(a=a, b=b, issuer_a=f"https://kc.test/realms/{a}")


@pytest.fixture
async def as_a(api: asyncpg.Connection, tenants: Tenants) -> asyncpg.Connection:
    await set_tenant(api, tenants.a)
    return api


@dataclass
class Nbo:
    conn: asyncpg.Connection
    person_id: uuid.UUID


@pytest.fixture
async def nbo(as_a: asyncpg.Connection) -> Nbo:
    """Section 3 of the check script: a mission, a hotel guest and an incident."""
    await as_a.execute(
        """
        INSERT INTO mission (tenant_id, code, city, country_code, location)
        VALUES (current_tenant_id(), 'NBO', 'Nairobi', 'KE', 'SRID=4326;POINT(36.8080 -1.2950)');
        INSERT INTO site (tenant_id, mission_id, site_type, name, location)
        SELECT current_tenant_id(), id, 'HOTEL', 'Hotel', 'SRID=4326;POINT(36.8240 -1.2975)'
          FROM mission WHERE code = 'NBO';
        """
    )
    person_id = uuid.uuid4()
    await as_a.execute(
        "INSERT INTO person (id, tenant_id, person_type, full_name) "
        "VALUES ($1, current_tenant_id(), 'DELEGATE', 'Test Delegate')",
        person_id,
    )
    await as_a.execute(
        "INSERT INTO person_location_current (person_id, tenant_id, location, confidence, "
        "primary_source) VALUES ($1, current_tenant_id(), 'SRID=4326;POINT(36.8240 -1.2975)', "
        "89, 'TRAVEL_BOOKING')",
        person_id,
    )
    await as_a.execute(
        "INSERT INTO incident (tenant_id, reference, title, category, severity, signal_severity, "
        "location) VALUES (current_tenant_id(), next_reference('INC', true), 'Unrest', "
        "'CIVIL_UNREST', 'CRITICAL', 'HIGH', 'SRID=4326;POINT(36.8245 -1.2838)')"
    )
    return Nbo(conn=as_a, person_id=person_id)


# --- 0-2: connection role, no tenant, issuer lookup --------------------------------


async def test_00_api_role_is_not_superuser_or_bypassrls(api: asyncpg.Connection) -> None:
    row = await api.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    assert row is not None
    assert not row["rolsuper"]
    assert not row["rolbypassrls"]


async def test_01_no_tenant_returns_zero_rows_without_error(db: DbUrls, nbo: Nbo) -> None:
    fresh = await asyncpg.connect(db.api_plain)
    try:
        assert await fresh.fetchval("SELECT count(*) FROM mission") == 0
    finally:
        await fresh.close()


async def test_02_resolve_tenant_by_issuer_works_before_tenant_is_set(
    api: asyncpg.Connection, tenants: Tenants
) -> None:
    assert await api.fetchval("SELECT resolve_tenant_by_issuer($1)", tenants.issuer_a) == tenants.a


async def test_03_tenant_table_hidden_without_tenant(
    api: asyncpg.Connection, tenants: Tenants
) -> None:
    assert await api.fetchval("SELECT count(*) FROM tenant") == 0


# --- 3: tenant A data ---------------------------------------------------------------


async def test_04_impact_zone_view_finds_hotel_guest(nbo: Nbo) -> None:
    rows = await nbo.conn.fetch("SELECT distance_m FROM v_incident_people_in_zone")
    assert len(rows) == 1
    assert 1400 < rows[0]["distance_m"] < 1600  # hotel is ~1.5 km from the epicentre


async def test_05_incident_severity_below_signal_severity_rejected(
    as_a: asyncpg.Connection,
) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await as_a.execute(
            "INSERT INTO incident (tenant_id, reference, title, category, severity, "
            "signal_severity, location) VALUES (current_tenant_id(), 'X', 't', 'C', 'LOW', "
            "'HIGH', 'SRID=4326;POINT(0 0)')"
        )


# --- 4: tenant B cannot see or write A's data -----------------------------------------


@pytest.fixture
async def as_b(nbo: Nbo, tenants: Tenants) -> asyncpg.Connection:
    await set_tenant(nbo.conn, tenants.b)
    return nbo.conn


async def test_06_tenant_b_sees_zero_missions(as_b: asyncpg.Connection) -> None:
    assert await as_b.fetchval("SELECT count(*) FROM mission") == 0


async def test_07_tenant_b_sees_zero_sites(as_b: asyncpg.Connection) -> None:
    assert await as_b.fetchval("SELECT count(*) FROM site") == 0


async def test_08_tenant_b_sees_only_its_own_tenant_row(as_b: asyncpg.Connection) -> None:
    names = [r["name"] for r in await as_b.fetch("SELECT name FROM tenant")]
    assert names == ["Tenant B"]


async def test_09_tenant_b_cannot_insert_rows_for_tenant_a(
    as_b: asyncpg.Connection, tenants: Tenants
) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        await as_b.execute(
            "INSERT INTO mission (tenant_id, code, city, country_code, location) "
            "VALUES ($1, 'X', 'X', 'XX', 'SRID=4326;POINT(0 0)')",
            tenants.a,
        )


async def test_10_api_cannot_create_tenants(as_b: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await as_b.execute("INSERT INTO tenant (name, oidc_issuer) VALUES ('evil', 'x')")


# --- 5: reference numbers -------------------------------------------------------------


async def test_11_next_reference_increments(nbo: Nbo) -> None:
    # The nbo fixture's incident used the first number.
    ref = await nbo.conn.fetchval("SELECT next_reference('INC', true)")
    assert re.fullmatch(r"INC-\d{4}-0002", ref)


# --- 6: audit chain ---------------------------------------------------------------------


@pytest.fixture
async def audited(as_a: asyncpg.Connection) -> asyncpg.Connection:
    await as_a.execute(
        """
        INSERT INTO audit_log (tenant_id, actor_type, action, entity_type, details) VALUES
          (current_tenant_id(), 'SYSTEM', 'TEST.ONE', 'test', '{"a":1}'),
          (current_tenant_id(), 'USER',   'TEST.TWO', 'test', '{"b":2}'),
          (current_tenant_id(), 'AGENT',  'TEST.THREE', 'test', '{}')
        """
    )
    return as_a


async def test_12_audit_chain_seq_and_links(audited: asyncpg.Connection) -> None:
    rows = await audited.fetch(
        "SELECT chain_seq, prev_hash, row_hash FROM audit_log ORDER BY chain_seq"
    )
    assert [r["chain_seq"] for r in rows] == [1, 2, 3]
    assert all(r["row_hash"] for r in rows)
    assert rows[0]["prev_hash"] is None
    assert [r["prev_hash"] for r in rows[1:]] == [r["row_hash"] for r in rows[:-1]]


async def test_13_audit_verify_chain_intact(audited: asyncpg.Connection) -> None:
    assert await audited.fetchval("SELECT audit_verify_chain()") is None


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_log SET action = 'X'", "DELETE FROM audit_log", "TRUNCATE audit_log"],
    ids=["14_update", "15_delete", "16_truncate"],
)
async def test_14_16_audit_mutation_blocked(audited: asyncpg.Connection, statement: str) -> None:
    with pytest.raises(DB_ERROR):
        await audited.execute(statement)


async def test_17_app_supplied_seq_and_hash_are_overwritten(audited: asyncpg.Connection) -> None:
    await audited.execute(
        "INSERT INTO audit_log (tenant_id, chain_seq, actor_type, action, entity_type, "
        "prev_hash, row_hash) VALUES (current_tenant_id(), 1, 'USER', 'FORGE', 'x', 'nope', "
        "'deadbeef')"
    )
    row = await audited.fetchrow("SELECT chain_seq, row_hash FROM audit_log WHERE action = 'FORGE'")
    assert row is not None
    assert row["chain_seq"] == 4
    assert row["row_hash"] != "deadbeef"
    assert await audited.fetchval("SELECT audit_verify_chain()") is None


# --- 7: agents and policies ----------------------------------------------------------------


@dataclass
class AgentWorld:
    conn: asyncpg.Connection
    hom: uuid.UUID
    hq: uuid.UUID
    agent: uuid.UUID
    p: dict[str, uuid.UUID]


@pytest.fixture
async def agents(as_a: asyncpg.Connection) -> AgentWorld:
    # IDs are fresh per test: the check script's fixed IDs would clash across tests.
    hom, hq, agent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    p = {k: uuid.uuid4() for k in ("msg", "unknown", "evac", "log")}
    await as_a.execute(
        "INSERT INTO role (tenant_id, code, name) "
        "VALUES (current_tenant_id(), 'DUTY_OFFICER', 'Duty')"
    )
    await as_a.executemany(
        "INSERT INTO app_user (id, tenant_id, external_id, email, display_name) "
        "VALUES ($1, current_tenant_id(), $2, $3, $4)",
        [(hom, "s1", "hom@x", "HoM"), (hq, "s2", "hq@x", "HQ")],
    )
    await as_a.execute(
        "INSERT INTO agent (id, tenant_id, code, name, autonomy_level) "
        "VALUES ($1, current_tenant_id(), 'COMMS', 'Comms', 0)",
        agent,
    )
    await as_a.execute(
        """
        INSERT INTO action_policy (tenant_id, action_type, min_autonomy_level, approver_roles, is_undoable) VALUES
          (current_tenant_id(), 'SEND_EXTERNAL_MESSAGE', 2, '{DUTY_OFFICER|CONSULAR_OFFICER}', false),
          (current_tenant_id(), 'START_EVACUATION', 3, '{HEAD_OF_MISSION,HQ_CRISIS_DIRECTOR}', false),
          (current_tenant_id(), 'LOG_INFO', 0, '{}', true)
        """  # noqa: E501
    )
    await as_a.executemany(
        "INSERT INTO agent_proposal (id, tenant_id, agent_id, proposal_key, action_type, title, "
        "proposed_action) VALUES ($1, current_tenant_id(), $2, $3, $4, 't', 'p')",
        [
            (p["msg"], agent, "k1", "SEND_EXTERNAL_MESSAGE"),
            (p["unknown"], agent, "k2", "NO_SUCH_ACTION"),
            (p["evac"], agent, "k3", "START_EVACUATION"),
            (p["log"], agent, "k4", "LOG_INFO"),
        ],
    )
    return AgentWorld(conn=as_a, hom=hom, hq=hq, agent=agent, p=p)


async def test_18_policy_level_3_with_one_approver_rejected(as_a: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await as_a.execute(
            "INSERT INTO action_policy (tenant_id, action_type, min_autonomy_level, "
            "approver_roles) VALUES (current_tenant_id(), 'BAD', 3, '{HEAD_OF_MISSION}')"
        )


async def _proposal(w: AgentWorld, key: str) -> asyncpg.Record:
    row = await w.conn.fetchrow(
        "SELECT p.effective_level, p.deadline_at, "
        "  (SELECT array_agg(required_role ORDER BY step_no) FROM proposal_approval a "
        "    WHERE a.proposal_id = p.id) AS roles "
        "FROM agent_proposal p WHERE p.id = $1",
        w.p[key],
    )
    assert row is not None
    return row


async def test_19_auto_agent_external_message_needs_one_approver(agents: AgentWorld) -> None:
    row = await _proposal(agents, "msg")
    assert row["effective_level"] == 2
    assert row["deadline_at"] is not None
    assert row["roles"] == ["DUTY_OFFICER|CONSULAR_OFFICER"]


async def test_20_unknown_action_is_advise_only(agents: AgentWorld) -> None:
    row = await _proposal(agents, "unknown")
    assert row["effective_level"] == 4
    assert row["roles"] is None


async def test_21_evacuation_needs_two_ordered_approvers(agents: AgentWorld) -> None:
    row = await _proposal(agents, "evac")
    assert row["effective_level"] == 3
    assert row["roles"] == ["HEAD_OF_MISSION", "HQ_CRISIS_DIRECTOR"]


async def test_22_undoable_log_info_stays_level_0(agents: AgentWorld) -> None:
    assert (await _proposal(agents, "log"))["effective_level"] == 0


async def test_23_app_cannot_change_effective_level(agents: AgentWorld) -> None:
    with pytest.raises(asyncpg.RaiseError, match="immutable"):
        await agents.conn.execute(
            "UPDATE agent_proposal SET effective_level = 0 WHERE id = $1", agents.p["evac"]
        )


async def test_24_app_cannot_change_action_payload(agents: AgentWorld) -> None:
    with pytest.raises(asyncpg.RaiseError, match="immutable"):
        await agents.conn.execute(
            """UPDATE agent_proposal SET action_payload = '{"x":1}' WHERE id = $1""",
            agents.p["msg"],
        )


DECIDE = (
    "UPDATE proposal_approval SET decision = $3, decided_by = $2, decided_at = now() "
    "WHERE proposal_id = $1 AND step_no = $4"
)


async def test_25_step_2_cannot_be_decided_before_step_1(agents: AgentWorld) -> None:
    with pytest.raises(asyncpg.RaiseError, match="earlier steps"):
        await agents.conn.execute(DECIDE, agents.p["evac"], agents.hq, "APPROVE", 2)


async def test_26_same_person_cannot_approve_step_2(agents: AgentWorld) -> None:
    await agents.conn.execute(DECIDE, agents.p["evac"], agents.hom, "APPROVE", 1)
    with pytest.raises(asyncpg.UniqueViolationError):
        await agents.conn.execute(DECIDE, agents.p["evac"], agents.hom, "APPROVE", 2)


async def test_27_a_decided_step_cannot_be_changed(agents: AgentWorld) -> None:
    await agents.conn.execute(DECIDE, agents.p["evac"], agents.hom, "APPROVE", 1)
    with pytest.raises(asyncpg.RaiseError, match="already decided"):
        await agents.conn.execute(
            "UPDATE proposal_approval SET decision = 'REJECT' WHERE proposal_id = $1 "
            "AND step_no = 1",
            agents.p["evac"],
        )


async def test_28_different_person_approves_step_2(agents: AgentWorld) -> None:
    await agents.conn.execute(DECIDE, agents.p["evac"], agents.hom, "APPROVE", 1)
    await agents.conn.execute(DECIDE, agents.p["evac"], agents.hq, "APPROVE", 2)
    approved = await agents.conn.fetchval(
        "SELECT count(*) FROM proposal_approval WHERE proposal_id = $1 AND decision = 'APPROVE'",
        agents.p["evac"],
    )
    assert approved == 2


async def test_29_approval_rows_cannot_be_created_pre_decided(agents: AgentWorld) -> None:
    with pytest.raises(asyncpg.RaiseError, match="undecided"):
        await agents.conn.execute(
            "INSERT INTO proposal_approval (tenant_id, proposal_id, step_no, required_role, "
            "decision, decided_by) VALUES (current_tenant_id(), $1, 9, 'X', 'APPROVE', $2)",
            agents.p["msg"],
            agents.hom,
        )


async def test_30_rejection_needs_a_reason(agents: AgentWorld) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await agents.conn.execute(
            "UPDATE agent_proposal SET status = 'REJECTED' WHERE id = $1", agents.p["msg"]
        )


# --- 8: kill switch --------------------------------------------------------------------------


async def test_31_kill_switch_blocks_new_proposals(agents: AgentWorld) -> None:
    await agents.conn.execute(
        "UPDATE tenant SET agents_paused = true, agents_paused_at = now() "
        "WHERE id = current_tenant_id()"
    )
    with pytest.raises(asyncpg.RaiseError, match="kill switch"):
        await agents.conn.execute(
            "INSERT INTO agent_proposal (tenant_id, agent_id, proposal_key, action_type, title, "
            "proposed_action) VALUES (current_tenant_id(), $1, 'k9', 'LOG_INFO', 't', 'p')",
            agents.agent,
        )


async def test_32_api_cannot_rename_its_tenant(as_a: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await as_a.execute("UPDATE tenant SET name = 'x'")


# --- 9: check-in history ----------------------------------------------------------------------


async def test_33_checkin_latest_answer_counts(nbo: Nbo) -> None:
    campaign = uuid.uuid4()
    await nbo.conn.execute(
        "INSERT INTO notification_campaign (id, tenant_id, reference, campaign_type, message, "
        "channels, created_by_type) VALUES ($1, current_tenant_id(), next_reference('NTF', false), "
        "'CHECKIN', 'Are you safe?', '{APP,SMS}', 'PLAYBOOK')",
        campaign,
    )
    await nbo.conn.execute(
        "INSERT INTO checkin_response (tenant_id, campaign_id, person_id, status, responded_at) "
        "VALUES (current_tenant_id(), $1, $2, 'SAFE', now() - interval '1 min'), "
        "(current_tenant_id(), $1, $2, 'NEED_HELP', now())",
        campaign,
        nbo.person_id,
    )
    assert await nbo.conn.fetchval("SELECT status FROM v_checkin_latest") == "NEED_HELP"


async def test_34_unknown_channel_rejected(as_a: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await as_a.execute(
            "INSERT INTO notification_campaign (tenant_id, reference, campaign_type, message, "
            "channels, created_by_type) VALUES (current_tenant_id(), 'N', 'ALERT', 'm', "
            "'{PIGEON}', 'USER')"
        )
