# tests/test_classifier.py
# Test suite for core/intent_classifier.py
# Run with: pytest tests/test_classifier.py -v

from pathlib import Path

from core.intent_classifier import IntentClassifier


def _write_skill(
    skills_dir: Path,
    skill_id: str,
    triggers: list[str],
    priority: int = 1,
) -> None:
    """Create a temporary skill with front matter for classifier tests."""
    skill_dir: Path = skills_dir / skill_id
    skill_dir.mkdir(parents=True)
    trigger_text: str = ", ".join(f"'{trigger}'" for trigger in triggers)
    skill_content: str = (
        "---\n"
        f"name: {skill_id}\n"
        f"description: Test skill {skill_id}\n"
        f"triggers: [{trigger_text}]\n"
        f"priority: {priority}\n"
        "---\n"
        "\n"
        f"# {skill_id}\n"
    )
    (skill_dir / "SKILL.md").write_text(skill_content, encoding="utf-8")


def test_classify_returns_correct_skill(tmp_path: Path) -> None:
    """Classifier returns a skill ID when at least two triggers match."""
    skills_dir: Path = tmp_path / "skills"
    _write_skill(skills_dir, "flask-rest-api", ["flask", "rest api"])

    classifier = IntentClassifier(str(skills_dir))

    assert classifier.classify("build a flask rest api endpoint") == ["flask-rest-api"]


def test_classify_requires_min_two_matches(tmp_path: Path) -> None:
    """Classifier returns no skills when only one trigger matches."""
    skills_dir: Path = tmp_path / "skills"
    _write_skill(skills_dir, "flask-rest-api", ["flask", "rest api"])

    classifier = IntentClassifier(str(skills_dir))

    assert classifier.classify("I want flask") == []


def test_classify_handles_negation(tmp_path: Path) -> None:
    """Classifier skips a trigger when it is preceded by negation."""
    skills_dir: Path = tmp_path / "skills"
    _write_skill(skills_dir, "flask-rest-api", ["flask", "rest api"])

    classifier = IntentClassifier(str(skills_dir))

    assert classifier.classify("build a rest api without flask") == []


def test_classify_matches_phrase_words_in_order(tmp_path: Path) -> None:
    """Classifier matches multi-word triggers when words appear in order."""
    skills_dir: Path = tmp_path / "skills"
    _write_skill(skills_dir, "pytest-generation", ["pytest", "write tests"])

    classifier = IntentClassifier(str(skills_dir))

    assert classifier.classify("write pytest tests for my module") == [
        "pytest-generation"
    ]


def test_classify_caps_at_max_skills(tmp_path: Path) -> None:
    """Classifier returns no more than two matching skill IDs."""
    skills_dir: Path = tmp_path / "skills"
    for index in range(4):
        _write_skill(
            skills_dir,
            f"skill-{index}",
            ["flask", "rest api"],
            priority=index,
        )

    classifier = IntentClassifier(str(skills_dir))

    assert len(classifier.classify("build a flask rest api endpoint")) <= 2


def test_build_skill_prompt_section_empty_on_no_match(tmp_path: Path) -> None:
    """Skill prompt section is empty when no skill IDs are provided."""
    classifier = IntentClassifier(str(tmp_path / "skills"))

    assert classifier.build_skill_prompt_section([]) == ""


def test_load_skill_content_returns_none_for_missing(tmp_path: Path) -> None:
    """Missing skills return None when content is requested."""
    skills_dir: Path = tmp_path / "skills"
    skills_dir.mkdir()
    classifier = IntentClassifier(str(skills_dir))

    assert classifier.load_skill_content("missing-skill") is None
