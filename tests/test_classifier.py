# tests/test_classifier.py
import os
import pytest
from pathlib import Path
from core.intent_classifier import IntentClassifier, SkillMeta, MIN_MATCHES

# ── Helper: create a temporary skills directory ──────────────────────


def make_skill_dir(
    tmp_path: Path, skill_id: str, triggers: list[str], priority: int = 1
) -> Path:
    """Create a minimal SKILL.md in a temp directory for testing."""
    skill_dir = tmp_path / skill_id
    skill_dir.mkdir()
    triggers_str = ", ".join(triggers)
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {skill_id}\n"
        f"description: Test skill for {skill_id}\n"
        f"triggers: [{triggers_str}]\n"
        f"priority: {priority}\n"
        f"max_tokens: 350\n"
        f"---\n\n"
        f"# {skill_id} Specialist\n\n"
        f"You are an expert in {skill_id}. Apply best practices.\n"
    )
    return skill_dir


# ── Tests ─────────────────────────────────────────────────────────────


def test_classifier_loads_skills_from_directory(tmp_path):
    make_skill_dir(tmp_path, "flask-api", ["flask", "rest api", "api server"])
    make_skill_dir(tmp_path, "debugging", ["debug", "error", "traceback"])

    classifier = IntentClassifier(skills_dir=str(tmp_path))
    assert len(classifier.skills) == 2
    skill_ids = [s.skill_id for s in classifier.skills]
    assert "flask-api" in skill_ids
    assert "debugging" in skill_ids


def test_classifier_returns_correct_skill(tmp_path):
    make_skill_dir(tmp_path, "flask-api", ["flask", "rest api", "api server", "crud"])
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    result = classifier.classify("build a flask rest api with crud endpoints")
    assert result == ["flask-api"]


def test_classifier_requires_minimum_two_matches(tmp_path):
    make_skill_dir(tmp_path, "flask-api", ["flask", "rest api", "api server"])
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    # Only one trigger word matches — should return empty
    result = classifier.classify("I want to use flask for something")
    assert result == []


def test_classifier_handles_negation(tmp_path):
    make_skill_dir(tmp_path, "flask-api", ["flask", "rest api", "api server", "crud"])
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    # "not flask" — negation should prevent flask from matching
    result = classifier.classify("build a rest api but not using flask, use fastapi instead")
    # Only "rest api" matches without negation, which is < MIN_MATCHES
    assert result == []


def test_classifier_caps_at_max_two_skills(tmp_path):
    for name, triggers in [
        ("skill-a", ["alpha", "bravo", "charlie"]),
        ("skill-b", ["delta", "echo", "foxtrot"]),
        ("skill-c", ["golf", "hotel", "india"]),
        ("skill-d", ["juliet", "kilo", "lima"]),
    ]:
        make_skill_dir(tmp_path, name, triggers)

    # Craft a prompt that matches all 4 skills
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    result = classifier.classify("alpha bravo delta echo golf hotel juliet kilo")
    assert len(result) <= 2


def test_classifier_no_match_returns_empty_list(tmp_path):
    make_skill_dir(tmp_path, "flask-api", ["flask", "rest api", "api server"])
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    result = classifier.classify("create a folder")
    assert result == []


def test_classifier_empty_skills_dir_returns_empty(tmp_path):
    empty_dir = tmp_path / "empty_skills"
    empty_dir.mkdir()
    classifier = IntentClassifier(skills_dir=str(empty_dir))
    result = classifier.classify("flask rest api backend")
    assert result == []


def test_classifier_missing_skills_dir_does_not_crash(tmp_path):
    classifier = IntentClassifier(skills_dir=str(tmp_path / "nonexistent"))
    result = classifier.classify("flask rest api")
    assert result == []


def test_load_skill_content_returns_string(tmp_path):
    make_skill_dir(tmp_path, "debugging", ["debug", "error", "traceback", "fix"])
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    content = classifier.load_skill_content("debugging")
    assert content is not None
    assert len(content) > 10


def test_load_skill_content_returns_none_for_missing(tmp_path):
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    content = classifier.load_skill_content("nonexistent-skill")
    assert content is None


def test_build_skill_prompt_section_returns_empty_for_no_match(tmp_path):
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    content, loaded_ids = classifier.build_skill_prompt_section([])
    assert content == ""
    assert loaded_ids == []


def test_build_skill_prompt_section_combines_two_skills(tmp_path):
    make_skill_dir(tmp_path, "flask-api", ["flask", "rest api", "api server"])
    make_skill_dir(tmp_path, "debugging", ["debug", "error", "traceback"])
    classifier = IntentClassifier(skills_dir=str(tmp_path))
    content, loaded_ids = classifier.build_skill_prompt_section(["flask-api", "debugging"])
    assert "SKILL SEPARATOR" in content
    assert len(loaded_ids) == 2


def test_classifier_runs_fast(tmp_path):
    """Classifier must complete in under 50ms for any prompt."""
    for i in range(10):
        make_skill_dir(
            tmp_path, f"skill-{i}", [f"trigger{i}a", f"trigger{i}b", f"trigger{i}c"]
        )

    classifier = IntentClassifier(skills_dir=str(tmp_path))

    import time

    start = time.monotonic()
    for _ in range(100):
        classifier.classify("build a trigger0a trigger0b application with trigger1a trigger1b")
    elapsed = time.monotonic() - start

    # 100 classifications should complete in under 1 second total
    assert elapsed < 1.0, f"Classifier too slow: 100 calls took {elapsed:.3f}s"
