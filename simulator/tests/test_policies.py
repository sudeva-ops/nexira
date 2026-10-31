"""The seeded policies and the action registry agree (review of Prompt 12)."""

from app.modules.agents.actions import ACTIONS

from nexira_sim.seed import data


def test_every_undoable_action_can_be_undone() -> None:
    """D-13: level 1 is allowed only for undoable actions, so each action a policy
    marks undoable needs an undo in the registry, or undo would always fail."""
    undoable = {action for action, _floor, _roles, is_undoable in data.POLICIES if is_undoable}
    assert undoable == {"LOG_INFO", "POST_INTERNAL_NOTE"}
    for action in undoable:
        assert ACTIONS[action].undo is not None, action


def test_every_seeded_action_type_can_execute() -> None:
    seeded = data.POLICIES + data.TRAVEL_POLICIES + data.DOCUMENT_POLICIES + data.HAZARD_POLICIES
    assert {action for action, *_ in seeded} <= set(ACTIONS)
    assert not any(undoable for _a, _f, _r, undoable, _d in data.DOCUMENT_POLICIES)
    # D-38: arming is never undone by the agent (a person disarms) and never Auto (§43 Q5).
    assert data.HAZARD_POLICIES == [
        ("ARM_PLAYBOOK", 2, ["SECURITY_OFFICER|DUTY_OFFICER"], False, 12 * 3600)
    ]
