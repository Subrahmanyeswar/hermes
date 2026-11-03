# core/pytest_recovery_engine.py
"""
Pytest Failure Recovery State Machine for HERMES (Section 9.4).
Replaces blind retry behavior with structured evidence capture, failure classification,
deterministic fingerprinting, no-progress suppression, and targeted repair ordering.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


class FailureClass(str, Enum):
    TEST_CONTRACT_DEFECT = "TEST_CONTRACT_DEFECT"
    APPLICATION_IMPLEMENTATION_DEFECT = "APPLICATION_IMPLEMENTATION_DEFECT"
    SYNTAX_OR_IMPORT_DEFECT = "SYNTAX_OR_IMPORT_DEFECT"
    ENVIRONMENT_OR_DEPENDENCY_DEFECT = "ENVIRONMENT_OR_DEPENDENCY_DEFECT"
    DATABASE_OR_STATE_DEFECT = "DATABASE_OR_STATE_DEFECT"
    BROWSER_INTEGRATION_DEFECT = "BROWSER_INTEGRATION_DEFECT"
    EXTERNAL_SERVICE_FAILURE = "EXTERNAL_SERVICE_FAILURE"
    UNKNOWN_DEFECT = "UNKNOWN_DEFECT"


@dataclass
class FailingTestItem:
    node_id: str
    failure_type: str
    message: str
    details: str = ""
    failure_class: FailureClass = FailureClass.UNKNOWN_DEFECT
    fingerprint: str = ""
    suggested_repair: str = ""


@dataclass
class PytestEvidenceRecord:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    failing_items: List[FailingTestItem] = field(default_factory=list)
    source_hashes: Dict[str, str] = field(default_factory=dict)
    junit_xml: Optional[str] = None
    is_no_progress: bool = False
    repair_order: List[str] = field(default_factory=list)


class PytestRecoveryEngine:
    """Manages failure analysis, fingerprinting, and recovery order for pytest runs."""

    def __init__(self, workspace_root: Optional[Path | str] = None, max_repairs_per_fingerprint: int = 2) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd()
        self.max_repairs_per_fingerprint = max_repairs_per_fingerprint
        self._fingerprint_history: Dict[str, int] = {}
        self._last_source_hashes: Dict[str, str] = {}

    def compute_source_hashes(self, extensions: Tuple[str, ...] = (".py", ".js", ".css", ".html")) -> Dict[str, str]:
        """Compute SHA-256 for all relevant source files in workspace."""
        hashes: Dict[str, str] = {}
        for ext in extensions:
            for p in self.workspace_root.glob(f"**/*{ext}"):
                if "venv" in p.parts or ".pytest_cache" in p.parts or "__pycache__" in p.parts:
                    continue
                try:
                    hashes[str(p.relative_to(self.workspace_root))] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
                except Exception:
                    pass
        return hashes

    def parse_and_classify(
        self,
        command: str,
        exit_code: int,
        stdout: str,
        stderr: str = "",
        junit_xml_path: Optional[Path | str] = None,
    ) -> PytestEvidenceRecord:
        """Step A & B: Capture failure evidence and classify each failure node."""
        source_hashes = self.compute_source_hashes()
        failing_items: List[FailingTestItem] = []

        # 1. Parse from JUnit XML if provided and valid
        if junit_xml_path and Path(junit_xml_path).exists():
            try:
                tree = ET.parse(str(junit_xml_path))
                root = tree.getroot()
                for testcase in root.iter("testcase"):
                    classname = testcase.get("classname", "")
                    name = testcase.get("name", "")
                    file_attr = testcase.get("file", "")
                    node_id = f"{file_attr}::{name}" if file_attr else f"{classname}.{name}"

                    for failure in testcase.findall("failure"):
                        msg = failure.get("message", "")
                        details = failure.text or ""
                        f_type = failure.get("type", "AssertionError")
                        item = self._create_classified_item(node_id, f_type, msg, details, source_hashes)
                        failing_items.append(item)

                    for error in testcase.findall("error"):
                        msg = error.get("message", "")
                        details = error.text or ""
                        f_type = error.get("type", "Error")
                        item = self._create_classified_item(node_id, f_type, msg, details, source_hashes)
                        failing_items.append(item)
            except Exception:
                pass

        # 2. Fallback: Parse from terminal stdout if XML was empty or unavailable
        if not failing_items and exit_code != 0:
            lines = stdout.splitlines()
            cur_node = ""
            for line in lines:
                m_fail = re.search(r'FAILED\s+([^\s:]+::\w+)(?:\s+-\s+(.+))?', line)
                if m_fail:
                    cur_node = m_fail.group(1)
                    inline_msg = m_fail.group(2)
                    if inline_msg:
                        item = self._create_classified_item(cur_node, "AssertionError", inline_msg.strip(), "", source_hashes)
                        failing_items.append(item)
                        cur_node = ""
                        continue
                elif ("assert" in line or "AssertionError" in line or "Error:" in line):
                    cur_msg = line.strip()
                    if cur_node:
                        item = self._create_classified_item(cur_node, "AssertionError", cur_msg, "", source_hashes)
                        failing_items.append(item)
                        cur_node = ""

            if cur_node and not any(it.node_id == cur_node for it in failing_items):
                item = self._create_classified_item(cur_node, "AssertionError", "Test failed assertion", "", source_hashes)
                failing_items.append(item)

            # Check syntax or collection errors
            if not failing_items:
                m_syn = re.search(r'ERROR collecting\s+([^\s]+)', stdout)
                if m_syn:
                    node_id = m_syn.group(1)
                    item = self._create_classified_item(node_id, "CollectionError", "Error during test collection", stdout, source_hashes)
                    failing_items.append(item)

        # 3. Check for No-Progress suppression (Step D)
        is_no_progress = False
        for item in failing_items:
            count = self._fingerprint_history.get(item.fingerprint, 0)
            if count >= self.max_repairs_per_fingerprint:
                # Same deterministic failure occurred again without source change
                is_no_progress = True
                break
            self._fingerprint_history[item.fingerprint] = count + 1

        # 4. Generate Test Execution Order (Step E)
        repair_order: List[str] = []
        if failing_items:
            # 1. Run the primary failed test node
            repair_order.append(f"pytest {failing_items[0].node_id} -v")
            # 2. Run the focused test module
            mod_path = failing_items[0].node_id.split("::")[0]
            repair_order.append(f"pytest {mod_path} -v")
            # 3. Run full regression battery
            repair_order.append("pytest tests/ -v")
            # 4. Run browser acceptance tests
            repair_order.append("browser e2e verification")

        self._last_source_hashes = source_hashes

        return PytestEvidenceRecord(
            command=command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            failing_items=failing_items,
            source_hashes=source_hashes,
            is_no_progress=is_no_progress,
            repair_order=repair_order,
        )

    def _create_classified_item(
        self,
        node_id: str,
        f_type: str,
        msg: str,
        details: str,
        source_hashes: Dict[str, str],
    ) -> FailingTestItem:
        f_class, repair = self._classify_failure(node_id, f_type, msg, details)
        # Compute stable fingerprint: sha256(node_id + failure_class + normalized_msg + combined_hash)
        norm_msg = re.sub(r'\s+', ' ', re.sub(r'0x[0-9a-fA-F]+', '0xADDR', msg)).strip()
        mod_file = node_id.split("::")[0]
        src_hash = source_hashes.get(mod_file, "no_hash")

        fp_raw = f"{node_id}:{f_class.value}:{norm_msg}:{src_hash}"
        fingerprint = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:16]

        return FailingTestItem(
            node_id=node_id,
            failure_type=f_type,
            message=msg,
            details=details,
            failure_class=f_class,
            fingerprint=fingerprint,
            suggested_repair=repair,
        )

    def _classify_failure(
        self,
        node_id: str,
        f_type: str,
        msg: str,
        details: str,
    ) -> Tuple[FailureClass, str]:
        """Classify failure and specify the single targeted root cause repair (Step B & C)."""
        combined = f"{msg} {details}".lower()

        # Rule 1: HTTP Status Code Expectation Contract Defect (e.g. 200 vs 201)
        if ("assert 201 == 200" in combined or "assert 200 == 201" in combined or
            ("status_code" in combined and "201" in combined and "200" in combined)):
            return (
                FailureClass.TEST_CONTRACT_DEFECT,
                "Update the test assertion to accept canonical HTTP 201 Created for resource creation."
            )

        # Rule 2: Syntax / Import Defect
        if any(k in combined for k in ("syntaxerror", "importerror", "modulenotfounderror", "cannot import name")):
            return (
                FailureClass.SYNTAX_OR_IMPORT_DEFECT,
                "Fix Python syntax or update module import path."
            )

        # Rule 3: Database / Foreign Key / State Defect
        if any(k in combined for k in ("sqlite3.", "integrityerror", "foreign key", "operationalerror", "check_same_thread", "programmingerror")):
            if "check_same_thread" in combined or "programmingerror" in combined:
                return (
                    FailureClass.DATABASE_OR_STATE_DEFECT,
                    "Pass check_same_thread=False to sqlite3.connect for async threadpool safety."
                )
            return (
                FailureClass.DATABASE_OR_STATE_DEFECT,
                "Fix database foreign key ordering or schema definition."
            )

        # Rule 4: Content-Type / CSV Export Defect
        if "text/csv" in combined or "content-type" in combined:
            return (
                FailureClass.APPLICATION_IMPLEMENTATION_DEFECT,
                "Ensure endpoint returns Response with media_type='text/csv' and Content-Disposition headers."
            )

        # Rule 5: Environment / Missing Dependency
        if "no module named" in combined and any(p in combined for p in ("fastapi", "uvicorn", "pydantic", "pytest")):
            return (
                FailureClass.ENVIRONMENT_OR_DEPENDENCY_DEFECT,
                "Verify canonical Python interpreter path and ensure required dependencies are installed."
            )

        # Rule 6: General Application Defect
        return (
            FailureClass.APPLICATION_IMPLEMENTATION_DEFECT,
            f"Fix application business logic for failing assertion: {msg[:100]}."
        )
