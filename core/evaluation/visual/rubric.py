# core/evaluation/visual/rubric.py
"""
Rubric configuration loader for Visual Evaluator (Prompt 17).
Loads YAML rubric definitions or falls back to built-in defaults.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.evaluation.visual.models import VisualCategory

logger = logging.getLogger("hermes.evaluation.visual.rubric")


@dataclass
class RubricCriterion:
    criterion_id: str
    category: VisualCategory
    name: str
    description: str
    weight: float = 1.0


@dataclass
class VisualRubric:
    version: str = "1.0.0"
    name: str = "Default Frontend Visual Rubric"
    pass_threshold: float = 0.70
    criteria: List[RubricCriterion] = field(default_factory=list)

    @classmethod
    def load_from_yaml(cls, path: Path | str) -> VisualRubric:
        p = Path(path)
        if not p.exists():
            return cls.default()

        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            criteria = []
            for item in data.get("criteria", []):
                cat_id = item.get("id", "DESIGN_QUALITY")
                try:
                    category = VisualCategory(cat_id)
                except ValueError:
                    category = VisualCategory.DESIGN_QUALITY

                criteria.append(
                    RubricCriterion(
                        criterion_id=cat_id,
                        category=category,
                        name=item.get("name", cat_id),
                        description=item.get("description", ""),
                        weight=float(item.get("weight", 1.0)),
                    )
                )

            return cls(
                version=data.get("version", "1.0.0"),
                name=data.get("name", "Loaded Rubric"),
                pass_threshold=float(data.get("pass_threshold", 0.70)),
                criteria=criteria,
            )
        except Exception as e:
            logger.warning(f"Error loading visual rubric from {path}: {e}")
            return cls.default()

    @classmethod
    def default(cls) -> VisualRubric:
        return cls(
            version="1.0.0",
            name="Default Frontend Visual Rubric",
            pass_threshold=0.70,
            criteria=[
                RubricCriterion("DESIGN_QUALITY", VisualCategory.DESIGN_QUALITY, "Design Quality", "Coherent visual language", 1.2),
                RubricCriterion("LAYOUT", VisualCategory.LAYOUT, "Layout", "Proper positioning & alignment", 1.2),
                RubricCriterion("VISUAL_HIERARCHY", VisualCategory.VISUAL_HIERARCHY, "Hierarchy", "Clear visual dominance", 1.0),
                RubricCriterion("TYPOGRAPHY", VisualCategory.TYPOGRAPHY, "Typography", "Readable scales & sizes", 0.8),
                RubricCriterion("SPACING", VisualCategory.SPACING, "Spacing", "Consistent margin/padding rhythm", 1.0),
                RubricCriterion("COLOR_CONTRAST", VisualCategory.COLOR_CONTRAST, "Color & Contrast", "Legible text contrast", 1.0),
                RubricCriterion("COMPONENT_CONSISTENCY", VisualCategory.COMPONENT_CONSISTENCY, "Component Consistency", "Unified controls", 0.8),
                RubricCriterion("RESPONSIVE_BEHAVIOR", VisualCategory.RESPONSIVE_BEHAVIOR, "Responsive Behavior", "Adapts across viewports", 1.5),
                RubricCriterion("INTERACTION_CLARITY", VisualCategory.INTERACTION_CLARITY, "Interaction Clarity", "Affordance of clickable elements", 0.8),
                RubricCriterion("ACCESSIBILITY_SIGNALS", VisualCategory.ACCESSIBILITY_SIGNALS, "Accessibility Signals", "Alt attributes & labels", 0.7),
            ],
        )
