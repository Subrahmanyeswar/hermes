# tests/test_phase11_alignment_verifier.py
"""
Adversarial Fixture Test Suite for HERMES Phase 11 (Stage 11.3).
Validates core/alignment_verifier.py against clean projects and 14+ failure modes.
All fixtures are created dynamically in isolated TemporaryDirectory sandboxes.
"""

import tempfile
from pathlib import Path
import pytest

from core.alignment_verifier import (
    verify_project_alignment,
    AlignmentReport,
    AlignmentDefect,
    DefectKind,
    DefectSeverity,
)
from core.contracts.blueprint import ImplementationBlueprint, FilePlan
from core.contracts.manifest import (
    InterfaceManifest,
    ElementContract,
    CssContract,
    JsModuleContract,
    NavLinkContract,
)
from core.contracts.rubric import QualityRubric


# ---------------------------------------------------------------------------
# Fixture 1: Positive Baseline (Clean Multi-Page Project)
# ---------------------------------------------------------------------------
def test_positive_baseline_clean_project():
    """Verify that a well-formed multi-page project passes all alignment checks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # Create files
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head>
    <title>Home</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header id="site-header">
        <nav id="main-nav">
            <a href="about.html">About</a>
            <a href="#features">Features</a>
        </nav>
    </header>
    <main id="features">
        <button id="cta-button" class="btn-primary">Click Me</button>
    </main>
    <img src="logo.png" alt="Logo">
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )

        (ws / "about.html").write_text(
            """<!DOCTYPE html>
<html>
<head>
    <title>About</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <header id="site-header">
        <nav id="main-nav">
            <a href="index.html">Home</a>
        </nav>
    </header>
    <section id="team">
        <h1 class="title">Our Team</h1>
    </section>
</body>
</html>""",
            encoding="utf-8",
        )

        (ws / "styles.css").write_text(
            """/* Clean styles */
:root {
    --primary-color: #007bff;
}
.btn-primary {
    background-color: var(--primary-color);
    color: #fff;
    padding: 10px 20px;
}
.title {
    font-size: 24px;
}
#site-header {
    padding: 20px;
}
""",
            encoding="utf-8",
        )

        (ws / "app.js").write_text(
            """// Clean application logic
document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('cta-button');
    if (btn) {
        btn.addEventListener('click', () => {
            console.log('Button clicked');
        });
    }
});
""",
            encoding="utf-8",
        )

        (ws / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\nfakeimage")

        # Create contracts
        bp = ImplementationBlueprint(
            planned_files=[
                FilePlan(path="index.html", purpose="Entrypoint"),
                FilePlan(path="about.html", purpose="About page"),
                FilePlan(path="styles.css", purpose="Styles"),
                FilePlan(path="app.js", purpose="App logic"),
                FilePlan(path="logo.png", purpose="Logo asset"),
            ]
        )

        manifest = InterfaceManifest(
            element_ids={
                "cta-button": ElementContract(dom_id="cta-button", tag="button", owning_file="index.html"),
                "features": ElementContract(dom_id="features", tag="main", owning_file="index.html"),
            },
            css_classes={
                "btn-primary": CssContract(class_name="btn-primary", owning_file="styles.css"),
            },
            navigation_links=[
                NavLinkContract(source_file="index.html", target_href="about.html"),
                NavLinkContract(source_file="index.html", target_href="#features"),
            ],
        )

        report = verify_project_alignment(ws, blueprint=bp, interface_manifest=manifest)

        assert report.status == "PASS"
        assert report.hard_error_count == 0
        assert len(report.defects) == 0
        assert report.report_hash != ""


# ---------------------------------------------------------------------------
# Fixture 2: Broken CSS Reference
# ---------------------------------------------------------------------------
def test_broken_css_reference():
    """Detect broken CSS reference in HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><link rel="stylesheet" href="missing.css"></head><body><h1>Hi</h1></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        assert report.hard_error_count >= 1
        kinds = [d.kind for d in report.defects]
        assert DefectKind.BROKEN_REFERENCE in kinds


# ---------------------------------------------------------------------------
# Fixture 3: Broken JS Reference
# ---------------------------------------------------------------------------
def test_broken_js_reference():
    """Detect broken JS script reference in HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><script src="nonexistent_script.js"></script></head><body><h1>Hi</h1></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        assert report.hard_error_count >= 1
        kinds = [d.kind for d in report.defects]
        assert DefectKind.BROKEN_REFERENCE in kinds


# ---------------------------------------------------------------------------
# Fixture 4: Missing DOM ID Referenced by JS
# ---------------------------------------------------------------------------
def test_missing_dom_id_in_js():
    """Detect when JS queries a DOM ID that does not exist in HTML."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><script src="app.js"></script></head><body><button id="real-btn">Click</button></body></html>""",
            encoding="utf-8",
        )
        (ws / "app.js").write_text(
            """const missing = document.getElementById('ghost-element');
const queryMissing = document.querySelector('#missing-div');
""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        missing_ids = [d.target for d in report.defects if d.kind == DefectKind.MISSING_DOM_ID]
        assert "ghost-element" in missing_ids
        assert "missing-div" in missing_ids


# ---------------------------------------------------------------------------
# Fixture 5: Missing Contract-Owned CSS Class
# ---------------------------------------------------------------------------
def test_missing_contract_owned_css_class():
    """Detect when InterfaceManifest expects a CSS class that stylesheet lacks."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><link rel="stylesheet" href="styles.css"></head><body><div class="card">Card</div></body></html>""",
            encoding="utf-8",
        )
        (ws / "styles.css").write_text(
            """.card { padding: 10px; }""",
            encoding="utf-8",
        )

        manifest = InterfaceManifest(
            css_classes={
                "btn-highlight": CssContract(class_name="btn-highlight", owning_file="styles.css"),
            }
        )

        report = verify_project_alignment(ws, interface_manifest=manifest)
        assert report.status == "FAIL"
        missing_classes = [d.target for d in report.defects if d.kind == DefectKind.MISSING_CSS_CLASS]
        assert "btn-highlight" in missing_classes


# ---------------------------------------------------------------------------
# Fixture 6: Dead Navigation Link
# ---------------------------------------------------------------------------
def test_dead_navigation_link():
    """Detect when <a href="..."> references a missing file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><body><a href="contact.html">Contact Us</a></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        dead_links = [d.target for d in report.defects if d.kind == DefectKind.DEAD_LINK]
        assert "contact.html" in dead_links


# ---------------------------------------------------------------------------
# Fixture 7: Dead Anchor Fragment
# ---------------------------------------------------------------------------
def test_dead_anchor_fragment():
    """Detect when link references an anchor that does not exist in target file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><body>
                <a href="#nonexistent-anchor">Internal Dead Anchor</a>
                <a href="page2.html#missing-section">External Dead Anchor</a>
            </body></html>""",
            encoding="utf-8",
        )
        (ws / "page2.html").write_text(
            """<!DOCTYPE html><html><body><div id="existing-section">Present</div></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        dead_anchors = [d.target for d in report.defects if d.kind == DefectKind.DEAD_ANCHOR]
        assert "#nonexistent-anchor" in dead_anchors
        assert "page2.html#missing-section" in dead_anchors


# ---------------------------------------------------------------------------
# Fixture 8: Duplicate DOM ID in Same Document
# ---------------------------------------------------------------------------
def test_duplicate_dom_id_in_same_document():
    """Detect duplicate id attribute inside the same HTML document."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><body>
                <div id="duplicate-item">First</div>
                <div id="duplicate-item">Second</div>
            </body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        dups = [d.target for d in report.defects if d.kind == DefectKind.DUPLICATE_DOM_ID]
        assert "duplicate-item" in dups


# ---------------------------------------------------------------------------
# Fixture 9: Multi-Page Valid ID Sharing (Cross-Page Reuse)
# ---------------------------------------------------------------------------
def test_multi_page_valid_id_sharing():
    """Confirm that the same DOM ID used on DIFFERENT pages is NOT flagged as duplicate."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><body><nav id="site-nav"><a href="about.html">About</a></nav></body></html>""",
            encoding="utf-8",
        )
        (ws / "about.html").write_text(
            """<!DOCTYPE html><html><body><nav id="site-nav"><a href="index.html">Home</a></nav></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        # Should not have duplicate DOM ID errors
        dup_defects = [d for d in report.defects if d.kind == DefectKind.DUPLICATE_DOM_ID]
        assert len(dup_defects) == 0


# ---------------------------------------------------------------------------
# Fixture 10: JS Module Import/Export Mismatch
# ---------------------------------------------------------------------------
def test_js_module_import_export_mismatch():
    """Detect when an ES module imports a symbol that the target module does not export."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "main.js").write_text(
            """import { calculateTotal, missingFunc } from './math.js';
console.log(calculateTotal(1, 2));
""",
            encoding="utf-8",
        )
        (ws / "math.js").write_text(
            """export function calculateTotal(a, b) {
    return a + b;
}
""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        unresolved = [d.target for d in report.defects if d.kind == DefectKind.UNRESOLVED_IMPORT]
        assert "missingFunc" in unresolved


# ---------------------------------------------------------------------------
# Fixture 11: Unplanned Manifest/Blueprint File (Strict Mode)
# ---------------------------------------------------------------------------
def test_unplanned_file_detection():
    """Detect files on disk that were not planned in the ImplementationBlueprint in strict mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text("<!DOCTYPE html><html><body>Home</body></html>", encoding="utf-8")
        (ws / "rogue_script.js").write_text("console.log('Unplanned');", encoding="utf-8")

        bp = ImplementationBlueprint(
            planned_files=[FilePlan(path="index.html", purpose="Entrypoint")]
        )

        report = verify_project_alignment(ws, blueprint=bp, strict_file_set=True)
        unplanned = [d.target for d in report.defects if d.kind == DefectKind.UNPLANNED_FILE]
        assert "rogue_script.js" in unplanned


# ---------------------------------------------------------------------------
# Fixture 12: Missing Planned File
# ---------------------------------------------------------------------------
def test_missing_planned_file():
    """Detect when a file specified in the ImplementationBlueprint is missing from disk."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text("<!DOCTYPE html><html><body>Home</body></html>", encoding="utf-8")

        bp = ImplementationBlueprint(
            planned_files=[
                FilePlan(path="index.html", purpose="Entrypoint"),
                FilePlan(path="missing_view.html", purpose="Missing View"),
            ]
        )

        report = verify_project_alignment(ws, blueprint=bp)
        assert report.status == "FAIL"
        missing = [d.target for d in report.defects if d.kind == DefectKind.MISSING_PLANNED_FILE]
        assert "missing_view.html" in missing


# ---------------------------------------------------------------------------
# Fixture 13: Dynamic Selector Limitation Handling
# ---------------------------------------------------------------------------
def test_dynamic_selector_warning_not_hard_error():
    """Confirm dynamic selectors yield WARNING/INFO, not a false-positive hard ERROR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><body><div id="item-1">Item 1</div></body></html>""",
            encoding="utf-8",
        )
        (ws / "app.js").write_text(
            """function getItem(id) {
    return document.getElementById('item-' + id);
}
const el = document.querySelector('#' + prefix);
""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        # Should not produce hard MISSING_DOM_ID errors for dynamic selectors
        hard_errors = [d for d in report.defects if d.severity == DefectSeverity.ERROR]
        assert len(hard_errors) == 0

        # Should record DYNAMIC_SELECTOR_UNVERIFIED
        dynamic_defects = [d for d in report.defects if d.kind == DefectKind.DYNAMIC_SELECTOR_UNVERIFIED]
        assert len(dynamic_defects) >= 1
        assert len(report.limitations) >= 1


# ---------------------------------------------------------------------------
# Fixture 14: Anti-Placeholder Detection
# ---------------------------------------------------------------------------
def test_anti_placeholder_detection():
    """Detect TODO comments, Lorem ipsum, and empty stubs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><body>
                <!-- TODO: implement header -->
                <p>Lorem ipsum dolor sit amet</p>
            </body></html>""",
            encoding="utf-8",
        )
        (ws / "stub.css").write_text("/* empty */", encoding="utf-8")
        (ws / "stub.js").write_text("// TODO: add code later\n", encoding="utf-8")

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        placeholders = [d for d in report.defects if d.kind == DefectKind.PLACEHOLDER_DETECTED]
        assert len(placeholders) >= 3


# ---------------------------------------------------------------------------
# Fixture 15: Path Traversal Containment Violation
# ---------------------------------------------------------------------------
def test_path_traversal_containment_violation():
    """Detect attempts to link outside workspace root via ../.."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head>
                <link rel="stylesheet" href="../../escape.css">
                <script src="../../../evil.js"></script>
            </head><body>
                <a href="../../../../sensitive_data.txt">Secret</a>
            </body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        traversals = [d for d in report.defects if d.kind == DefectKind.PATH_TRAVERSAL_VIOLATION]
        assert len(traversals) >= 3


# ---------------------------------------------------------------------------
# Fixture 16: Determinism Verification
# ---------------------------------------------------------------------------
def test_verifier_determinism():
    """Ensure running verifier twice on identical filesystem produces identical report hash."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text("<!DOCTYPE html><html><body><h1>Test</h1></body></html>", encoding="utf-8")
        (ws / "styles.css").write_text("h1 { color: red; }", encoding="utf-8")

        report1 = verify_project_alignment(ws)
        report2 = verify_project_alignment(ws)

        assert report1.report_hash == report2.report_hash
        assert report1.status == report2.status
        assert report1.to_dict() == report2.to_dict()


# ---------------------------------------------------------------------------
# Fixture 17: Discovery Fallback Mode (No Contracts Supplied)
# ---------------------------------------------------------------------------
def test_discovery_fallback_mode():
    """Verify that verifier operates seamlessly with zero contracts provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head>
            <body><h1 id="header">Hello</h1><script src="script.js"></script></body></html>""",
            encoding="utf-8",
        )
        (ws / "style.css").write_text("#header { font-size: 20px; }", encoding="utf-8")
        (ws / "script.js").write_text(
            "const h = document.getElementById('header'); console.log(h);",
            encoding="utf-8",
        )

        # Call with blueprint=None, interface_manifest=None, quality_rubric=None
        report = verify_project_alignment(ws)
        assert report.status == "PASS"
        assert report.hard_error_count == 0
# ---------------------------------------------------------------------------
# Targeted Verification Closure: 1. Discovery-Fallback Negative Test
# ---------------------------------------------------------------------------
def test_discovery_fallback_negative_broken_project():
    """
    Discovery mode negative test: When no contracts are supplied, verifier must
    NOT pass a broken project merely because contracts are absent.
    Must detect broken asset references and missing DOM IDs as hard errors.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head>
                <link rel="stylesheet" href="missing_theme.css">
                <script src="missing_bundle.js"></script>
            </head><body>
                <h1 id="title">Home</h1>
                <script src="app.js"></script>
            </body></html>""",
            encoding="utf-8",
        )
        (ws / "app.js").write_text(
            """const el = document.getElementById("ghost_element");
console.log(el);
""",
            encoding="utf-8",
        )

        # Deliberately supply NO contracts
        report = verify_project_alignment(ws, blueprint=None, interface_manifest=None, quality_rubric=None)

        assert report.status == "FAIL"
        assert report.hard_error_count >= 3

        defects = report.defects
        broken_refs = [d.target for d in defects if d.kind == DefectKind.BROKEN_REFERENCE]
        missing_ids = [d.target for d in defects if d.kind == DefectKind.MISSING_DOM_ID]

        assert "missing_theme.css" in broken_refs
        assert "missing_bundle.js" in broken_refs
        assert "ghost_element" in missing_ids


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 2. Parser Robustness - HTML
# ---------------------------------------------------------------------------
def test_parser_robustness_html_attributes_and_urls():
    """
    HTML parser robustness: quoted attributes, nested markup, query parameters
    in URLs, and cross-document anchor verification.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
    <header id="site-header">
        <div class="container 'highlighted' data-wrap">
            <nav id="nav-bar">
                <!-- Query string and anchor in same URL -->
                <a href="detail.html?tab=specs&view=full#specifications">Specs</a>
            </nav>
        </div>
    </header>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "detail.html").write_text(
            """<!DOCTYPE html>
<html>
<head><title>Detail</title></head>
<body>
    <header id="site-header">
        <nav id="nav-bar">
            <a href="index.html">Home</a>
        </nav>
    </header>
    <main id="specifications">
        <h2>Specifications</h2>
    </main>
</body>
</html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "PASS"
        assert report.hard_error_count == 0


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 2. Parser Robustness - CSS
# ---------------------------------------------------------------------------
def test_parser_robustness_css_selectors_and_urls():
    """
    CSS parser robustness: pseudo-classes, pseudo-elements, media queries,
    nested grouping, comments/strings containing selector text, and CSS url() assets.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "bg.png").write_bytes(b"dummy_png_bytes")

        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><link rel="stylesheet" href="style.css"></head>
            <body><div class="card grid icon">Content</div></body></html>""",
            encoding="utf-8",
        )

        (ws / "style.css").write_text(
            """/* .fake-comment-class #fake-comment-id */
.icon {
    content: ".fake-string-class #fake-string-id";
    background-image: url("bg.png");
    background-color: #fff;
}
.missing-asset {
    background-image: url("missing_texture.png");
}
.traversal-asset {
    background-image: url("../../outside.png");
}
/* Media queries and nested grouping */
@media screen and (min-width: 768px) {
    .grid { display: flex; }
}
@supports (display: grid) {
    .card { display: grid; }
}
/* Pseudo-classes and pseudo-elements */
a:hover, button:focus, .btn:active { color: blue; }
.card::before, .card::after { content: ""; }
/* Element and attribute selectors */
h1, h2, nav > ul > li { margin: 0; }
[data-active="true"] { opacity: 1; }
""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"

        broken_refs = [d.target for d in report.defects if d.kind == DefectKind.BROKEN_REFERENCE]
        traversals = [d.target for d in report.defects if d.kind == DefectKind.PATH_TRAVERSAL_VIOLATION]

        assert "missing_texture.png" in broken_refs
        assert "../../outside.png" in traversals

        # Pseudo-classes and valid selectors must NOT become false positive errors
        errors = [d.message for d in report.defects if d.severity == DefectSeverity.ERROR]
        assert not any("fake-comment-class" in m for m in errors)
        assert not any("fake-string-class" in m for m in errors)


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 2. Parser Robustness - JavaScript
# ---------------------------------------------------------------------------
def test_parser_robustness_js_selectors_and_syntax():
    """
    JS parser robustness: literal selectors, comments/strings containing selector text,
    template literals, event delegation, and real syntax errors.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head><script src="app.js"></script></head>
            <body><button id="save-btn">Save</button><div id="list"></div></body></html>""",
            encoding="utf-8",
        )
        (ws / "app.js").write_text(
            """// document.getElementById('comment-fake-id');
/* document.getElementById('block-comment-fake-id'); */
const advice = "Do not use document.getElementById('string-fake-id')";
const btn = document.getElementById('save-btn');
const container = document.getElementById('list');
container.addEventListener('click', (e) => {
    if (e.target.matches('.item')) {
        console.log('Delegated click');
    }
});
""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "PASS", f"Defects: {[d.to_dict() for d in report.defects]}"
        assert report.hard_error_count == 0

        # Now introduce a genuine syntax error in a script
        (ws / "broken.js").write_text("function badSyntax( {", encoding="utf-8")
        report2 = verify_project_alignment(ws)
        assert report2.status == "FAIL"
        syntax_defects = [d for d in report2.defects if d.kind == DefectKind.SYNTAX_ERROR]
        assert len(syntax_defects) >= 1


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 3. Filesystem Containment - Parent Traversal
# ---------------------------------------------------------------------------
def test_containment_parent_traversal():
    """Parent directory traversal escaping workspace is strictly rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html><html><head>
                <link rel="stylesheet" href="../../escape.css">
                <script src="../../../evil.js"></script>
            </head><body>
                <a href="../../../../sensitive_data.txt">Secret</a>
            </body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws)
        assert report.status == "FAIL"
        traversals = [d for d in report.defects if d.kind == DefectKind.PATH_TRAVERSAL_VIOLATION]
        assert len(traversals) >= 3


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 3. Filesystem Containment - Sibling Directory
# ---------------------------------------------------------------------------
def test_containment_sibling_directory_prefix_attack():
    """
    Sibling-directory prefix attack (e.g. 'hermes-evil' vs 'hermes')
    must be strictly rejected by component-aware path containment.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        parent = Path(tmpdir)
        ws_root = parent / "hermes"
        ws_root.mkdir()
        sibling_evil = parent / "hermes-evil"
        sibling_evil.mkdir()

        (sibling_evil / "malicious.js").write_text("alert('pwned');", encoding="utf-8")

        (ws_root / "index.html").write_text(
            """<!DOCTYPE html><html><head>
                <script src="../hermes-evil/malicious.js"></script>
            </head><body><h1>Hi</h1></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws_root)
        assert report.status == "FAIL"
        traversals = [d for d in report.defects if d.kind == DefectKind.PATH_TRAVERSAL_VIOLATION]
        assert len(traversals) >= 1


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 3. Filesystem Containment - File Symlink Escape
# ---------------------------------------------------------------------------
def test_containment_file_symlink_escape():
    """
    Symlink escape targeting file outside workspace.
    Explicitly reports a justified skip if symlink creation is not permitted.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        parent = Path(tmpdir)
        ws_root = parent / "hermes"
        ws_root.mkdir()
        outside_dir = parent / "outside"
        outside_dir.mkdir()
        secret_file = outside_dir / "secret.env"
        secret_file.write_text("SECRET=12345", encoding="utf-8")

        symlink_file = ws_root / "leak.env"
        try:
            symlink_file.symlink_to(secret_file)
            symlink_created = True
        except (OSError, NotImplementedError, PermissionError):
            symlink_created = False

        if not symlink_created:
            pytest.skip("File symlink creation not permitted in this Windows unprivileged environment")

        (ws_root / "index.html").write_text(
            """<!DOCTYPE html><html><body><a href="leak.env">Leak</a></body></html>""",
            encoding="utf-8",
        )

        report = verify_project_alignment(ws_root)
        assert report.status == "FAIL"
        traversals = [d for d in report.defects if d.kind == DefectKind.PATH_TRAVERSAL_VIOLATION]
        assert len(traversals) >= 1


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 3. Filesystem Containment - Directory Junction Escape
# ---------------------------------------------------------------------------
def test_containment_directory_junction_escape():
    """
    Windows directory junction escape targeting outside directory.
    Explicitly reports a justified skip if junction creation fails or platform unsupported.
    """
    import subprocess
    import sys

    if sys.platform != "win32":
        pytest.skip("Windows directory junctions are only applicable on win32 platform")

    with tempfile.TemporaryDirectory() as tmpdir:
        parent = Path(tmpdir)
        ws_root = parent / "hermes"
        ws_root.mkdir()
        outside_dir = parent / "outside"
        outside_dir.mkdir()
        (outside_dir / "passwords.txt").write_text("admin:secret", encoding="utf-8")

        junction_dir = ws_root / "junction_out"

        res = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction_dir), str(outside_dir)],
            capture_output=True,
            text=True,
        )

        if res.returncode != 0:
            pytest.skip(f"Junction creation not available: {res.stderr}")

        try:
            (ws_root / "index.html").write_text(
                """<!DOCTYPE html><html><body><a href="junction_out/passwords.txt">Secrets</a></body></html>""",
                encoding="utf-8",
            )

            report = verify_project_alignment(ws_root)
            assert report.status == "FAIL"
            traversals = [d for d in report.defects if d.kind == DefectKind.PATH_TRAVERSAL_VIOLATION]
            assert len(traversals) >= 1
        finally:
            subprocess.run(["cmd", "/c", "rmdir", str(junction_dir)], capture_output=True)


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 4. Quality Rubric - Short Complete Utility
# ---------------------------------------------------------------------------
def test_quality_rubric_short_complete_utility_passes():
    """
    Proves that a short (18-line), complete, working utility passes verification
    when it satisfies its applicable functional requirements, proving raw line
    counts are diagnostic signals rather than universal proof of failure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)
        (ws / "index.html").write_text(
            """<!DOCTYPE html>
<html>
<head>
    <title>Color Picker</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <input type="color" id="picker" value="#ff0000">
    <div id="preview" class="color-box"></div>
    <script src="app.js"></script>
</body>
</html>""",
            encoding="utf-8",
        )
        (ws / "style.css").write_text(
            """.color-box {
    width: 100px;
    height: 100px;
    border: 1px solid #000;
}
""",
            encoding="utf-8",
        )
        (ws / "app.js").write_text(
            """document.addEventListener('DOMContentLoaded', () => {
    const picker = document.getElementById('picker');
    const preview = document.getElementById('preview');
    picker.addEventListener('input', (e) => {
        preview.style.backgroundColor = e.target.value;
    });
});
""",
            encoding="utf-8",
        )

        rubric = QualityRubric(
            task_type="vanilla_web",
            complexity_profile="SIMPLE",
            expected_loc_bounds={"index.html": {"min_lines": 50, "max_lines": 200}},
        )

        report = verify_project_alignment(ws, quality_rubric=rubric)
        assert report.status == "PASS"
        assert report.hard_error_count == 0


# ---------------------------------------------------------------------------
# Targeted Verification Closure: 4. Quality Rubric - Bloated Placeholder Fails
# ---------------------------------------------------------------------------
def test_quality_rubric_large_placeholder_fails():
    """
    Proves that a large (300+ line) file that contains TODO placeholders
    or empty stub handlers fails quality verification despite its size.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = Path(tmpdir)

        # Generate a bloated 300-line HTML file containing a TODO comment
        bloated_lines = ["<!DOCTYPE html><html><body>"]
        for i in range(250):
            bloated_lines.append(f"<p>Paragraph line {i} of content</p>")
        bloated_lines.append("<!-- TODO: implement real interactive controls -->")
        bloated_lines.append("</body></html>")

        (ws / "index.html").write_text("\n".join(bloated_lines), encoding="utf-8")

        rubric = QualityRubric(
            task_type="vanilla_web",
            complexity_profile="LARGE",
            expected_loc_bounds={"index.html": {"min_lines": 100, "max_lines": 1000}},
        )

        report = verify_project_alignment(ws, quality_rubric=rubric)
        assert report.status == "FAIL"
        placeholders = [d for d in report.defects if d.kind == DefectKind.PLACEHOLDER_DETECTED]
        assert len(placeholders) >= 1
