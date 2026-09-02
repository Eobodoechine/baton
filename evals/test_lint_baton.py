#!/usr/bin/env python3
"""Structural and exit-code tests for lint_baton.py."""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lint_baton as lint  # noqa: E402


def valid_body():
    example_repo = os.path.abspath(os.path.join(os.sep, "tmp", "example"))
    return """# BATON — test
Detail tier: brief
Repo: {example_repo}
Card: .baton/PROJECT_CARD.md @ deadbeef
Trust rule: verify this file against the repository.

## 1. DO THIS NOW
Run: python -m pytest
Expected: green

## 2. WHERE YOU ARE
Run: git status

## 3. THE TASK
1. Do the work.

## 4. DO NOT RETRY
none

## 5. USER'S WORDS
none recorded

## 6. RULES THAT BIND THIS TASK
- Stay in scope.

## 11. DONE MEANS
python -m pytest exits zero. REPEAT: python -m pytest
""".format(example_repo=example_repo)


def write(tmp_path, body=None):
    path = tmp_path / "BATON.md"
    path.write_text(body if body is not None else valid_body())
    return path


def test_valid_baton_conforms(tmp_path):
    assert lint.check(str(write(tmp_path)), "brief") == []


def test_fenced_heading_does_not_satisfy_mandatory_section(tmp_path):
    body = valid_body().replace(
        "## 4. DO NOT RETRY\nnone",
        "## 9. GOTCHAS\n```markdown\n## 4. DO NOT RETRY\n```",
    )
    bad = lint.check(str(write(tmp_path, body)), "brief")
    assert any("missing mandatory section: ## 4" in item for item in bad)


def test_empty_mandatory_section_fails(tmp_path):
    body = valid_body().replace("## 4. DO NOT RETRY\nnone", "## 4. DO NOT RETRY")
    bad = lint.check(str(write(tmp_path, body)), "brief")
    assert any("present but empty: ## 4" in item for item in bad)


def test_header_fields_inside_fence_do_not_count(tmp_path):
    body = valid_body().replace(
        "Card: .baton/PROJECT_CARD.md @ deadbeef\nTrust rule: verify this file against the repository.",
        "```\nCard: .baton/PROJECT_CARD.md @ deadbeef\nTrust rule: example only\n```",
    )
    bad = lint.check(str(write(tmp_path, body)), "brief")
    assert any("Trust rule" in item for item in bad)
    assert any("Card:" in item for item in bad)


def test_missing_input_has_distinct_exit_code(tmp_path):
    run = subprocess.run(
        [sys.executable, os.path.join(HERE, "lint_baton.py"), str(tmp_path / "missing")],
        capture_output=True, text=True,
    )
    assert run.returncode == lint.EXIT_INPUT_ERROR
    assert "INPUT ERROR" in run.stderr


def test_repo_identity_must_match_when_relay_root_is_supplied(tmp_path):
    path = write(tmp_path)
    bad = lint.check(str(path), "brief", repo_root=str(tmp_path))
    assert any("does not match" in item for item in bad)
