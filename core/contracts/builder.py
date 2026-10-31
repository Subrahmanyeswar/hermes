# core/contracts/builder.py
"""
Contract Builder for HERMES Phase 5.
Derives durable, machine-verifiable implementation contracts:
  - ImplementationBlueprint (planned files, components, routes, data models)
  - InterfaceManifest (element IDs, CSS classes, event hooks, modules, forms, assets, breakpoints)
  - QualityRubric (hard requirements, quality dimensions, anti-placeholder rules)

Ensures that user prompt and mission goals are translated into explicit, verifiable
contracts before code generation, against which the actual workspace is evaluated.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from core.contracts.blueprint import (
    ImplementationBlueprint,
    FilePlan,
    ComponentSpec,
    RouteSpec,
    DataModelSpec,
)
from core.contracts.manifest import (
    InterfaceManifest,
    ElementContract,
    CssContract,
    JsHookContract,
    JsModuleContract,
    NavLinkContract,
    AssetContract,
    StateContract,
    FormContract,
    ApiEndpointContract,
)
from core.contracts.rubric import (
    QualityRubric,
    RubricRequirement,
    QualityDimension,
)
from core.contracts.validator import ContractValidator, ContractValidationResult


class ContractBuilder:
    """
    Authoritative factory for deriving implementation contracts from user requirements.
    """

    @classmethod
    def derive_contracts_for_mission(
        cls,
        mission_id: str,
        prompt: str,
        project_type: str = "vanilla_web",
        delivery_mode: str = "file_system",
        workspace_root: Optional[Path | str] = None,
    ) -> Tuple[ImplementationBlueprint, InterfaceManifest, QualityRubric]:
        """
        Derive a cohesive (Blueprint, Manifest, Rubric) tuple from a mission prompt.
        """
        p_lower = prompt.lower()

        # 1. Determine project type from prompt if generic
        if "python" in p_lower and not any(kw in p_lower for kw in ("website", "html", "web app", "webapp")):
            project_type = "python_project"
        elif any(kw in p_lower for kw in ("web", "html", "css", "javascript", "website", "board", "portal")):
            project_type = "vanilla_web"

        if project_type == "vanilla_web":
            return cls.build_web_contract(
                mission_id=mission_id,
                prompt=prompt,
                delivery_mode=delivery_mode,
            )
        else:
            return cls.build_python_contract(
                mission_id=mission_id,
                prompt=prompt,
                delivery_mode=delivery_mode,
            )

    @classmethod
    def build_web_contract(
        cls,
        mission_id: str,
        prompt: str,
        delivery_mode: str = "file_system",
        extra_files: Optional[List[str]] = None,
    ) -> Tuple[ImplementationBlueprint, InterfaceManifest, QualityRubric]:
        """
        Builds contracts for a web application mission.
        """
        p_lower = prompt.lower()
        mid = mission_id or f"m_{uuid.uuid4().hex[:8]}"

        # --- 1. Planned Files ---
        planned_files = [
            FilePlan(
                path="index.html",
                purpose="Primary application HTML entrypoint and semantic markup",
                role="entrypoint",
                dependencies=[],
                min_lines=15,
            ),
            FilePlan(
                path="styles.css",
                purpose="Application stylesheet with responsive design, grid/flex layout, and styling",
                role="style",
                dependencies=["index.html"],
                min_lines=15,
            ),
            FilePlan(
                path="app.js",
                purpose="Application logic, interactive event handlers, and DOM rendering",
                role="logic",
                dependencies=["index.html"],
                min_lines=20,
            ),
        ]
        if extra_files:
            for ef in extra_files:
                norm_ef = ef.replace("\\", "/").lstrip("./")
                if not any(f.path == norm_ef for f in planned_files):
                    planned_files.append(
                        FilePlan(
                            path=norm_ef,
                            purpose=f"Supporting artifact for {norm_ef}",
                            role="component",
                            dependencies=["index.html"],
                            min_lines=10,
                        )
                    )

        # --- 2. Element IDs & Controls ---
        element_ids: Dict[str, ElementContract] = {
            "app": ElementContract(
                dom_id="app",
                tag="div",
                owning_file="index.html",
                purpose="Main application container",
                required=True,
            ),
            "header": ElementContract(
                dom_id="header",
                tag="header",
                owning_file="index.html",
                purpose="Application navigation and title header",
                required=True,
            ),
        }

        # Contextual elements based on mission domain
        forms: Dict[str, FormContract] = {}
        js_hooks: Dict[str, JsHookContract] = {}

        if any(kw in p_lower for kw in ("event", "board", "campus")):
            element_ids["eventList"] = ElementContract(
                dom_id="eventList",
                tag="section",
                owning_file="index.html",
                purpose="Container displaying event cards",
                required=True,
            )
            element_ids["searchInput"] = ElementContract(
                dom_id="searchInput",
                tag="input",
                owning_file="index.html",
                purpose="Search input for filtering events",
                required=True,
            )
            element_ids["categoryFilter"] = ElementContract(
                dom_id="categoryFilter",
                tag="select",
                owning_file="index.html",
                purpose="Dropdown filter for event categories",
                required=True,
            )
            element_ids["eventForm"] = ElementContract(
                dom_id="eventForm",
                tag="form",
                owning_file="index.html",
                purpose="Form to create new events",
                required=True,
            )
            element_ids["submitButton"] = ElementContract(
                dom_id="submitButton",
                tag="button",
                owning_file="index.html",
                purpose="Submit button for creating events",
                required=True,
            )
            forms["eventForm"] = FormContract(
                form_id="eventForm",
                owning_file="index.html",
                fields=["title", "date", "category"],
                submit_handler="handleCreateEvent",
            )
            js_hooks["#searchInput"] = JsHookContract(
                hook_name="#searchInput",
                event_type="input",
                handler_name="handleSearch",
                owning_file="app.js",
                target_id="searchInput",
                purpose="Filter events dynamically as user types",
            )
            js_hooks["#eventForm"] = JsHookContract(
                hook_name="#eventForm",
                event_type="submit",
                handler_name="handleCreateEvent",
                owning_file="app.js",
                target_id="eventForm",
                purpose="Handle form submission and persist event",
            )
        elif any(kw in p_lower for kw in ("todo", "task", "tracker")):
            element_ids["todoForm"] = ElementContract(
                dom_id="todoForm",
                tag="form",
                owning_file="index.html",
                purpose="Form to create new tasks",
                required=True,
            )
            element_ids["todoInput"] = ElementContract(
                dom_id="todoInput",
                tag="input",
                owning_file="index.html",
                purpose="Input for task title",
                required=True,
            )
            element_ids["todoList"] = ElementContract(
                dom_id="todoList",
                tag="ul",
                owning_file="index.html",
                purpose="Container displaying task items",
                required=True,
            )
            element_ids["addTodoBtn"] = ElementContract(
                dom_id="addTodoBtn",
                tag="button",
                owning_file="index.html",
                purpose="Button to add task",
                required=True,
            )
            forms["todoForm"] = FormContract(
                form_id="todoForm",
                owning_file="index.html",
                fields=["task"],
                submit_handler="handleAddTodo",
            )
            js_hooks["#todoForm"] = JsHookContract(
                hook_name="#todoForm",
                event_type="submit",
                handler_name="handleAddTodo",
                owning_file="app.js",
                target_id="todoForm",
                purpose="Add new todo item to list",
            )
        else:
            # Generic interactive application elements
            element_ids["mainContent"] = ElementContract(
                dom_id="mainContent",
                tag="main",
                owning_file="index.html",
                purpose="Primary content display area",
                required=True,
            )
            element_ids["actionButton"] = ElementContract(
                dom_id="actionButton",
                tag="button",
                owning_file="index.html",
                purpose="Interactive primary trigger button",
                required=True,
            )
            js_hooks["#actionButton"] = JsHookContract(
                hook_name="#actionButton",
                event_type="click",
                handler_name="handleAction",
                owning_file="app.js",
                target_id="actionButton",
                purpose="Handle primary action click",
            )

        # --- 3. CSS Classes & Breakpoints ---
        css_classes: Dict[str, CssContract] = {
            "container": CssContract(
                class_name="container",
                owning_file="styles.css",
                target_elements=["body", "main"],
                styles_summary="Centering and max-width layout container",
            ),
            "btn": CssContract(
                class_name="btn",
                owning_file="styles.css",
                target_elements=["button", "a"],
                styles_summary="Button styling with hover and active states",
            ),
            "card": CssContract(
                class_name="card",
                owning_file="styles.css",
                target_elements=["div", "article"],
                styles_summary="Card component container with border or shadow",
            ),
        }

        breakpoints = {
            "mobile": "480px",
            "tablet": "768px",
            "desktop": "1024px",
        }

        # --- 4. Quality Rubric ---
        hard_reqs = [
            RubricRequirement(
                req_id="REQ-FILES",
                title="Required File Integrity",
                description="index.html, styles.css, and app.js must exist and contain non-empty implementation",
                rule_type="static_check",
                is_mandatory=True,
            ),
            RubricRequirement(
                req_id="REQ-LINKS",
                title="Resource Link Integrity",
                description="index.html must reference styles.css and app.js correctly without 404 or path traversal",
                rule_type="static_check",
                is_mandatory=True,
            ),
            RubricRequirement(
                req_id="REQ-DOM-ALIGNMENT",
                title="Cross-File DOM Alignment",
                description="All DOM elements queried by JavaScript must exist with exact matching IDs in HTML",
                rule_type="static_check",
                is_mandatory=True,
            ),
            RubricRequirement(
                req_id="REQ-SYNTAX",
                title="Syntax and Structural Sanity",
                description="JavaScript and CSS must have balanced braces and pass syntax inspection",
                rule_type="static_check",
                is_mandatory=True,
            ),
            RubricRequirement(
                req_id="REQ-ANTI-PLACEHOLDER",
                title="No Stubs or Placeholders",
                description="Codebase must not contain TODO comments, lorem ipsum, or empty handler stubs",
                rule_type="static_check",
                is_mandatory=True,
            ),
        ]

        # Add domain-specific requirement
        if any(kw in p_lower for kw in ("responsive", "mobile")):
            hard_reqs.append(
                RubricRequirement(
                    req_id="REQ-RESPONSIVE",
                    title="Responsive Layout",
                    description="Stylesheet must contain @media queries or responsive flex/grid layout rules",
                    rule_type="static_check",
                    is_mandatory=True,
                )
            )

        quality_dims = {
            "functional_depth": QualityDimension(
                dimension_name="functional_depth",
                weight=1.0,
                threshold=0.8,
                criteria=["Real event listeners attached", "Dynamic DOM updates implemented"],
            ),
            "visual_polish": QualityDimension(
                dimension_name="visual_polish",
                weight=0.8,
                threshold=0.7,
                criteria=["Structured color palette", "Typography styling", "Responsive rules"],
            ),
        }

        # --- Assemble Contracts ---
        blueprint = ImplementationBlueprint(
            mission_id=mid,
            project_type="vanilla_web",
            delivery_mode=delivery_mode,
            user_requirements=[prompt],
            acceptance_criteria=[req.description for req in hard_reqs],
            planned_files=planned_files,
            complexity_profile="SIMPLE",
        )

        manifest = InterfaceManifest(
            mission_id=mid,
            html_entrypoints=["index.html"],
            css_breakpoints=breakpoints,
            element_ids=element_ids,
            css_classes=css_classes,
            js_hooks=js_hooks,
            forms=forms,
        )

        rubric = QualityRubric(
            mission_id=mid,
            task_type="vanilla_web",
            complexity_profile="SIMPLE",
            hard_requirements=hard_reqs,
            quality_dimensions=quality_dims,
        )

        return blueprint, manifest, rubric

    @classmethod
    def build_python_contract(
        cls,
        mission_id: str,
        prompt: str,
        delivery_mode: str = "file_system",
    ) -> Tuple[ImplementationBlueprint, InterfaceManifest, QualityRubric]:
        """
        Builds contracts for a Python application or CLI mission.
        """
        mid = mission_id or f"m_{uuid.uuid4().hex[:8]}"

        planned_files = [
            FilePlan(
                path="main.py",
                purpose="Main application entrypoint and CLI driver",
                role="entrypoint",
                min_lines=15,
            ),
        ]

        hard_reqs = [
            RubricRequirement(
                req_id="REQ-PY-SYNTAX",
                title="Python AST Parse",
                description="main.py must be valid Python 3 syntax parseable by AST",
                rule_type="static_check",
                is_mandatory=True,
            ),
            RubricRequirement(
                req_id="REQ-NON-EMPTY",
                title="Non-Empty Implementation",
                description="Python files must contain executable logic without stubs",
                rule_type="static_check",
                is_mandatory=True,
            ),
        ]

        blueprint = ImplementationBlueprint(
            mission_id=mid,
            project_type="python_project",
            delivery_mode=delivery_mode,
            user_requirements=[prompt],
            acceptance_criteria=[req.description for req in hard_reqs],
            planned_files=planned_files,
            complexity_profile="SIMPLE",
        )

        manifest = InterfaceManifest(
            mission_id=mid,
            html_entrypoints=[],
        )

        rubric = QualityRubric(
            mission_id=mid,
            task_type="python_project",
            complexity_profile="SIMPLE",
            hard_requirements=hard_reqs,
        )

        return blueprint, manifest, rubric
