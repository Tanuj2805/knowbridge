"""The red-team suite (redteam/cases.py) against the guard's rules, offline: every attack question
is refused, every ordinary question passes, every planted attack is cut from its source and every
ordinary message comes through untouched. Live runs against the real model: redteam/live.py."""

import pytest

from app import guard
from redteam.cases import CASES, SOURCES

BLOCK = [c for c in CASES if c.expect == "block"]
PASS = [c for c in CASES if c.expect == "pass"]


@pytest.mark.parametrize("case", BLOCK, ids=[c.id for c in BLOCK])
def test_attack_questions_are_refused(case):
    assert guard.screen_question(case.text).blocked, case.text


@pytest.mark.parametrize("case", PASS, ids=[c.id for c in PASS])
def test_ordinary_questions_pass(case):
    assert not guard.screen_question(case.text).blocked, case.text


@pytest.mark.parametrize("src", SOURCES, ids=[s.id for s in SOURCES])
def test_planted_attacks_are_cut_and_team_talk_is_kept(src):
    s = guard.screen_source(src.text)
    if src.expect_cut:
        assert s.removed and not any(w in s.text for w in ("Mallory", "evil.example", "2030", "cancelled"))
    else:
        assert s.removed == 0 and s.text == guard.fence(guard.clean(src.text))


def test_the_real_fact_next_to_an_attack_survives():
    s = guard.screen_source(SOURCES[0].text)
    assert "Kestrel launch is on 5 Dec." in s.text
