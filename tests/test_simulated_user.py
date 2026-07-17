from __future__ import annotations

import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.simulated_user import SimulatedUserSession, build_simulator_contract


def user_case(seed: int = 7, max_turns: int = 4, stall_turns: int = 2) -> dict:
    return {
        "id": "progressive-user",
        "split": "held_in",
        "tags": ["capability", "positive"],
        "trials": 1,
        "seeds": [seed],
        "input": {"initial_user_message": "I need help with my account."},
        "simulated_user": {
            "persona": "A cautious account owner.",
            "private_truth": [
                {"id": "tier", "value": "My plan is enterprise.", "reveal_on": ["plan", "tier"]},
                {"id": "region", "value": "My region is Australia.", "reveal_on": ["region", "country"]},
            ],
            "disclosure_policy": {
                "mode": "progressive",
                "max_facts_per_turn": 1,
                "fallback": "next_unrevealed",
            },
            "termination": {
                "success_condition": "The account question is resolved.",
                "max_turns": max_turns,
                "stall_turns": stall_turns,
            },
        },
        "expected": {
            "outcome": "Resolve the account request.",
            "trajectory": {"required_tools": [], "forbidden_tools": [], "ordered_tools": []},
        },
        "graders": {
            "deterministic": [{"id": "safe", "check": "no_error", "arguments": {}}],
            "rubrics": [
                {
                    "id": "resolution",
                    "criterion": "The account request is resolved.",
                    "evidence": "final_output",
                    "threshold": 0.8,
                }
            ],
        },
    }


def test_private_truth_is_available_to_simulator_but_not_target_opening() -> None:
    contract = build_simulator_contract(user_case())

    assert "enterprise" in contract.simulator_prompt
    assert "Australia" in contract.simulator_prompt
    assert "enterprise" not in json.dumps(contract.target_opening)
    assert contract.target_opening == {"role": "user", "content": "I need help with my account."}


def test_progressive_disclosure_reveals_only_the_fact_directly_requested() -> None:
    session = SimulatedUserSession.from_case(user_case())

    turn = session.respond("Which plan or tier are you on?", "I can answer that.")

    assert turn.kind == "message"
    assert turn.text == "My plan is enterprise."
    assert turn.disclosed_fact_ids == ("tier",)
    assert "Australia" not in turn.text


def test_unrequested_private_fact_is_removed_from_proposed_message() -> None:
    session = SimulatedUserSession.from_case(user_case())

    turn = session.respond("How can I help?", "My plan is enterprise and my region is Australia.")

    assert turn.text == "My plan is enterprise."
    assert turn.disclosed_fact_ids == ("tier",)
    assert "Australia" not in turn.text


def test_duplicate_messages_progress_then_end_instead_of_stalling() -> None:
    session = SimulatedUserSession.from_case(user_case(stall_turns=1))
    first = session.respond("Tell me more.", "Please help with my account.")
    second = session.respond("Anything else?", "Please help with my account.")
    third = session.respond("Anything else?", "Please help with my account.")

    assert first.text == "Please help with my account."
    assert second.disclosed_fact_ids == ("tier",)
    assert third.disclosed_fact_ids == ("region",)
    assert session.respond("Anything else?", "Please help with my account.").kind == "end"


def test_duplicate_is_never_emitted_before_stall_limit() -> None:
    session = SimulatedUserSession.from_case(user_case(stall_turns=2))
    session.respond("Continue", "same reply")

    repeated = session.respond("Continue", "same reply")

    assert repeated.text != "same reply"
    assert repeated.disclosed_fact_ids == ("tier",)


def test_explicit_satisfaction_terminates_conversation() -> None:
    session = SimulatedUserSession.from_case(user_case())

    turn = session.respond("Your account is fixed.", "Thanks.", satisfied=True)

    assert turn.kind == "end"
    assert turn.reason == "success condition reached"


def test_turn_limit_terminates_within_configured_bound() -> None:
    session = SimulatedUserSession.from_case(user_case(max_turns=2))

    assert session.respond("First", "First reply").kind == "message"
    assert session.respond("Second", "Second reply").kind == "message"
    final = session.respond("Third", "Third reply")

    assert final.kind == "end"
    assert final.reason == "maximum turns reached"


def test_seed_produces_repeatable_fallback_disclosure_order() -> None:
    first = SimulatedUserSession.from_case(user_case(seed=31, stall_turns=1))
    second = SimulatedUserSession.from_case(user_case(seed=31, stall_turns=1))

    first.respond("Continue", "same")
    second.respond("Continue", "same")

    assert first.respond("Continue", "same") == second.respond("Continue", "same")
