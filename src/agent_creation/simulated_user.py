from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Literal

from .eval_design import EvalDesignError, validate_case


@dataclass(frozen=True)
class SimulatorContract:
    simulator_prompt: str
    target_opening: dict[str, str]


@dataclass(frozen=True)
class UserTurn:
    kind: Literal["message", "end"]
    text: str = ""
    disclosed_fact_ids: tuple[str, ...] = ()
    reason: str = ""


def normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())


def build_simulator_contract(case: dict[str, Any]) -> SimulatorContract:
    issues = validate_case(case, 0)
    if issues:
        raise EvalDesignError(issues)
    simulated_user = case["simulated_user"]
    prompt = "\n".join(
        [
            "Act only as the user in this evaluation.",
            f"Persona: {simulated_user['persona']}",
            f"Private truth: {json.dumps(simulated_user['private_truth'], sort_keys=True)}",
            f"Disclosure policy: {json.dumps(simulated_user['disclosure_policy'], sort_keys=True)}",
            f"Termination: {json.dumps(simulated_user['termination'], sort_keys=True)}",
            "Reveal only policy-permitted facts, never more than the per-turn limit, and do not repeat messages.",
        ]
    )
    return SimulatorContract(
        simulator_prompt=prompt,
        target_opening={"role": "user", "content": case["input"]["initial_user_message"]},
    )


@dataclass
class SimulatedUserSession:
    facts: tuple[dict[str, Any], ...]
    max_turns: int
    stall_turns: int
    max_facts_per_turn: int
    fallback: str
    seed: int
    turns: int = 0
    disclosed: set[str] = field(default_factory=set)
    messages: list[str] = field(default_factory=list)
    duplicate_count: int = 0

    @classmethod
    def from_case(cls, case: dict[str, Any], trial_index: int = 0) -> "SimulatedUserSession":
        issues = validate_case(case, 0)
        if issues:
            raise EvalDesignError(issues)
        if not 0 <= trial_index < case["trials"]:
            raise EvalDesignError(["trial index is outside configured seeds"])
        simulated_user = case["simulated_user"]
        policy = simulated_user["disclosure_policy"]
        termination = simulated_user["termination"]
        return cls(
            facts=tuple(simulated_user["private_truth"]),
            max_turns=termination["max_turns"],
            stall_turns=termination["stall_turns"],
            max_facts_per_turn=policy["max_facts_per_turn"],
            fallback=policy["fallback"],
            seed=case["seeds"][trial_index],
        )

    def respond(
        self,
        assistant_message: str,
        proposed_message: str,
        satisfied: bool = False,
    ) -> UserTurn:
        if satisfied:
            return UserTurn(kind="end", reason="success condition reached")
        if self.turns >= self.max_turns:
            return UserTurn(kind="end", reason="maximum turns reached")
        requested = self._requested_facts(assistant_message)
        if requested:
            return self._disclose(requested[: self.max_facts_per_turn])
        leaked = self._leaked_facts(proposed_message)
        if leaked:
            return self._disclose(leaked[: self.max_facts_per_turn])
        normalized = normalize(proposed_message)
        duplicate = not normalized or normalized in {normalize(message) for message in self.messages}
        if duplicate:
            self.duplicate_count += 1
            fallback = self._undisclosed_facts()
            if fallback and self.fallback == "next_unrevealed":
                return self._disclose(fallback[: self.max_facts_per_turn])
            return UserTurn(kind="end", reason="no new information to disclose")
        else:
            self.duplicate_count = 0
        self.turns += 1
        self.messages.append(proposed_message)
        return UserTurn(kind="message", text=proposed_message)

    def _requested_facts(self, assistant_message: str) -> list[dict[str, Any]]:
        normalized = normalize(assistant_message)
        return [
            fact
            for fact in self._undisclosed_facts()
            if any(normalize(trigger) in normalized for trigger in fact["reveal_on"])
        ]

    def _leaked_facts(self, proposed_message: str) -> list[dict[str, Any]]:
        normalized = normalize(proposed_message)
        return [
            fact
            for fact in self._undisclosed_facts()
            if normalize(fact["value"]) in normalized
        ]

    def _undisclosed_facts(self) -> list[dict[str, Any]]:
        return [fact for fact in self.facts if fact["id"] not in self.disclosed]

    def _disclose(self, facts: list[dict[str, Any]]) -> UserTurn:
        identifiers = tuple(fact["id"] for fact in facts)
        text = " ".join(fact["value"] for fact in facts)
        self.disclosed.update(identifiers)
        self.turns += 1
        self.duplicate_count = 0
        self.messages.append(text)
        return UserTurn(kind="message", text=text, disclosed_fact_ids=identifiers)
