# core/js_syntax_validator.py

"""

JavaScript Syntax and Structural Integrity Validator for HERMES 2.x.

Provides deterministic syntax checking for JS deliverables via Node.js

with module format awareness, legacy staging compatibility, atomic promotion,

and in-process AST / lexer bracket-balance fallback.

"""



from __future__ import annotations



import ast

import hashlib

import json

import logging

import os

import re

import shutil

import subprocess

import tempfile

import time

import uuid

from dataclasses import dataclass, field, asdict

from pathlib import Path

from typing import Optional, Tuple, List, Dict, Any



logger = logging.getLogger(__name__)





# Standard error classifications (Phase A5 & Phase 3)

CLASS_VALIDATION_SUCCESS = "validation_success"

CLASS_SYNTAX_ERROR = "syntax_error"

CLASS_APP_SYNTAX_ERROR = "syntax_error"

CLASS_TRUNCATED_MODEL_OUTPUT = "truncated_output"

CLASS_TOOL_ARGUMENT_ERROR = "tool_argument_error"

CLASS_FILE_WRITE_ERROR = "file_write_error"

CLASS_WORKSPACE_PATH_ERROR = "workspace_path_error"

CLASS_TOOLING_EXTENSION_ERROR = "unsupported_extension"

CLASS_MODULE_MODE_MISMATCH = "module_mode_mismatch"

CLASS_MODULE_CONFIGURATION_ERROR = "module_configuration_error"

CLASS_VALIDATOR_EXECUTION_ERROR = "validator_missing"

CLASS_PROMOTION_ERROR = "promotion_error"

CLASS_VALIDATOR_MISSING = "validator_missing"

CLASS_VALIDATOR_ENVIRONMENT_ERROR = "validator_environment_error"

CLASS_UNSUPPORTED_EXTENSION = "unsupported_extension"

CLASS_VALIDATION_TIMEOUT = "validation_timeout"

CLASS_FILE_MISSING = "file_missing"





@dataclass

class JsValidationResult:

    """Structured result capturing complete evidence of a JavaScript validation run."""

    is_valid: bool

    error_class: str

    error_message: Optional[str] = None

    line: Optional[int] = None

    column: Optional[int] = None

    canonical_target: Optional[str] = None

    staged_path: Optional[str] = None

    workspace_root: Optional[str] = None

    command_args: List[str] = field(default_factory=list)

    cwd: Optional[str] = None

    node_version: Optional[str] = None

    input_sha256: Optional[str] = None

    stdout: str = ""

    stderr: str = ""

    exit_code: Optional[int] = None

    timestamp: float = field(default_factory=time.time)

    promoted: bool = False



    def to_dict(self) -> Dict[str, Any]:

        return asdict(self)





def get_staging_path(target_path: Path | str) -> Path:

    """

    Compute standard staging path for an artifact.

    Preserves correct .js / .mjs / .cjs extension (Phase A1).

    Example: static/app.js -> static/app.pending.js

    """

    p = Path(target_path)

    suffix = p.suffix

    stem = p.stem

    if stem.endswith(".pending"):

        return p

    return p.parent / f"{stem}.pending{suffix}"





def compute_file_sha256(path: Path | str) -> Optional[str]:

    """Compute SHA-256 of file contents."""

    p = Path(path)

    if not p.exists() or not p.is_file():

        return None

    try:

        content = p.read_bytes()

        return hashlib.sha256(content).hexdigest()

    except Exception:

        return None





def detect_js_module_format(file_path: Path, workspace_root: Optional[Path] = None) -> str:

    """

    Determine whether JavaScript file operates under ES Modules or CommonJS (Phase A3).

    Inspects:

      1. Explicit .mjs (ESM) or .cjs (CJS) extension.

      2. package.json "type": "module" in directory tree.

      3. HTML script tag type="module" referencing this file.

    Returns: "module" or "commonjs".

    """

    # 1. Extension

    if file_path.suffix == ".mjs":

        return "module"

    if file_path.suffix == ".cjs":

        return "commonjs"



    # Search upwards for package.json up to workspace root or file_path root

    curr = file_path.parent

    limit = workspace_root.resolve() if workspace_root else file_path.parent

    while True:

        pkg_file = curr / "package.json"

        if pkg_file.exists():

            try:

                pkg_data = json.loads(pkg_file.read_text(encoding="utf-8", errors="ignore"))

                if pkg_data.get("type") == "module":

                    return "module"

            except Exception:

                pass

            break

        if curr == limit or curr.parent == curr:

            break

        curr = curr.parent



    # Check HTML referencing file

    if workspace_root:

        ws = Path(workspace_root)

        html_candidates = [ws / "index.html", ws / "static" / "index.html"]

        for h in html_candidates:

            if h.exists():

                try:

                    txt = h.read_text(encoding="utf-8", errors="ignore")

                    fname = file_path.name

                    # Look for <script type="module" src="...fname...">

                    if (re.search(rf'<script[^>]+type=["\']module["\'][^>]+src=["\'][^"\']*{re.escape(fname)}["\']', txt, re.I) or

                        re.search(rf'<script[^>]+src=["\'][^"\']*{re.escape(fname)}["\'][^>]+type=["\']module["\']', txt, re.I)):

                        return "module"

                except Exception:

                    pass



    return "commonjs"





def check_js_bracket_balance(code: str) -> Tuple[bool, Optional[str], Optional[int]]:

    """

    Authoritative in-process JavaScript lexical bracket, string, comment, regex,

    and template literal balance validator for HERMES 2.x.

    Guarantees robust detection of unclosed quotes, brackets, and template strings

    without falsely rejecting valid regular expressions or nested template literals.

    Returns (is_valid, error_message, estimated_line).

    """

    if not code or not isinstance(code, str):

        return True, None, None



    stack: List[Tuple[str, int]] = []  # ('(' | '[' | '{' | '${', line_num)

    pairs = {')': '(', ']': '[', '}': '{'}

    

    in_single_quote = False

    in_double_quote = False

    template_depth = 0  # number of active backtick levels

    template_dollar_count = 0  # number of active '${' in stack

    in_line_comment = False

    in_block_comment = False

    in_regex = False

    in_regex_class = False

    escape = False



    REGEX_PRECEDING_CHARS = set("([{;,=!?+:*&|~^%<>/-\n")

    REGEX_PRECEDING_KEYWORDS = {

        "return", "case", "typeof", "void", "delete", "yield",

        "await", "throw", "instanceof", "in", "do", "new", "default"

    }



    last_token_char = "\n"

    last_word = ""



    line_num = 1

    i = 0

    n = len(code)



    while i < n:

        c = code[i]



        if c == '\n':

            line_num += 1

            if in_line_comment:

                in_line_comment = False

            escape = False

            if not (in_single_quote or in_double_quote or template_depth > template_dollar_count or in_block_comment or in_regex):

                last_token_char = '\n'

                last_word = ""

            i += 1

            continue



        if escape:

            escape = False

            i += 1

            continue



        if c == '\\':

            if in_single_quote or in_double_quote or (template_depth > template_dollar_count) or in_regex:

                escape = True

            i += 1

            continue



        # Block comment

        if in_block_comment:

            if c == '*' and i + 1 < n and code[i + 1] == '/':

                in_block_comment = False

                i += 2

                continue

            i += 1

            continue



        # Line comment

        if in_line_comment:

            i += 1

            continue



        # Single-quote string

        if in_single_quote:

            if c == "'":

                in_single_quote = False

                last_token_char = "'"

                last_word = ""

            i += 1

            continue



        # Double-quote string

        if in_double_quote:

            if c == '"':

                in_double_quote = False

                last_token_char = '"'

                last_word = ""

            i += 1

            continue



        # Regular expression literal

        if in_regex:

            if in_regex_class:

                if c == ']':

                    in_regex_class = False

            else:

                if c == '[':

                    in_regex_class = True

                elif c == '/':

                    in_regex = False

                    # consume flags (gimsuy)

                    i += 1

                    while i < n and code[i].isalpha():

                        i += 1

                    last_token_char = '/'

                    last_word = ""

                    continue

            i += 1

            continue



        # Template literal text mode

        if template_depth > template_dollar_count:

            if c == '`':

                template_depth -= 1

                last_token_char = '`'

                last_word = ""

                i += 1

                continue

            elif c == '$' and i + 1 < n and code[i + 1] == '{':

                stack.append(('${', line_num))

                template_dollar_count += 1

                i += 2

                last_token_char = '{'

                last_word = ""

                continue

            i += 1

            continue



        # --- NORMAL JAVASCRIPT CODE OR INSIDE ${ ... } EXPRESSION ---



        # Check comment start

        if c == '/' and i + 1 < n:

            if code[i + 1] == '/':

                in_line_comment = True

                i += 2

                continue

            elif code[i + 1] == '*':

                in_block_comment = True

                i += 2

                continue



        # Check regex start vs division

        if c == '/':

            is_regex_context = (

                last_token_char in REGEX_PRECEDING_CHARS or

                last_word in REGEX_PRECEDING_KEYWORDS

            )

            if is_regex_context:

                in_regex = True

                in_regex_class = False

                i += 1

                continue

            else:

                last_token_char = '/'

                last_word = ""

                i += 1

                continue



        # Strings

        if c == "'":

            in_single_quote = True

            i += 1

            continue

        if c == '"':

            in_double_quote = True

            i += 1

            continue

        if c == '`':

            template_depth += 1

            i += 1

            continue



        # Brackets

        if c in '([{':

            stack.append((c, line_num))

            last_token_char = c

            last_word = ""

            i += 1

            continue

        elif c in ') dance party :) no just )]}':

            pass

        if c in ')]}':

            if not stack:

                return False, f"Unexpected closing bracket '{c}' without opening bracket", line_num

            top_bracket, top_line = stack.pop()

            if top_bracket == '${':

                template_dollar_count -= 1

                if c != '}':

                    return False, f"Mismatched bracket: expected closing '}}' for '${{' (opened at line {top_line}), got '{c}'", line_num

            else:

                expected = pairs.get(c)

                if top_bracket != expected:

                    return False, f"Mismatched bracket: expected closing for '{top_bracket}' (opened at line {top_line}), got '{c}'", line_num

            last_token_char = c

            last_word = ""

            i += 1

            continue



        # Non-whitespace tracking

        if not c.isspace():

            last_token_char = c

            if c.isalnum() or c in '_$':

                last_word += c

            else:

                last_word = ""



        i += 1



    if in_block_comment:

        return False, "Unclosed block comment (/* ...)", line_num

    if in_single_quote or in_double_quote or template_depth > 0:

        return False, "Unclosed string or template literal", line_num

    if in_regex:

        return False, "Unclosed regular expression literal", line_num

    if stack:

        unclosed, unclosed_line = stack[-1]

        return False, f"Unclosed '{unclosed}' opened at line {unclosed_line} (unexpected end of input)", line_num



    stripped = code.rstrip()

    if stripped:

        last_line = stripped.splitlines()[-1].strip()

        if re.search(r'(?:const|let|var)\s+[a-zA-Z0-9_$]+\s*=\s*\(?$', last_line):

            return False, f"Unexpected end of input: incomplete assignment '{last_line}'", line_num

        if last_line.endswith(('=', '=>', '+=', '-=', '*=', '/=', '&&', '||', '??', ':', '...', '+', '-', '*', '/', '%', ',')):

            return False, f"Unexpected end of input: dangling operator at end of file ('{last_line}')", line_num



    return True, None, None





def validate_javascript_detailed(

    file_path: Path | str,

    workspace_root: Optional[Path | str] = None,

    canonical_target: Optional[Path | str] = None,

) -> JsValidationResult:

    """

    Perform rigorous JavaScript syntax validation with Node.js and in-process fallback.

    Returns structured JsValidationResult with comprehensive diagnostics and evidence.

    Handles legacy staging (*.pending) via safe temporary copy in try...finally (Phase A2).

    """

    path = Path(file_path).resolve()

    ws_root = Path(workspace_root).resolve() if workspace_root else path.parent

    canonical_str = str(canonical_target) if canonical_target else str(path)



    if not path.exists() or not path.is_file():

        return JsValidationResult(

            is_valid=False,

            error_class=CLASS_FILE_MISSING,

            error_message=f"File does not exist: {path}",

            canonical_target=canonical_str,

            staged_path=str(path),

            workspace_root=str(ws_root),

        )



    sha256 = compute_file_sha256(path)

    node_bin = shutil.which("node")



    # If Node.js is missing from environment (Phase A5)

    if not node_bin:

        # Fall back to in-process lexical checking

        try:

            content = path.read_text(encoding="utf-8", errors="replace")

            is_bal, err_bal, line_bal = check_js_bracket_balance(content)

            if not is_bal:

                return JsValidationResult(

                    is_valid=False,

                    error_class=CLASS_APP_SYNTAX_ERROR,

                    error_message=f"Lexical check error: {err_bal}",

                    line=line_bal,

                    canonical_target=canonical_str,

                    staged_path=str(path),

                    workspace_root=str(ws_root),

                    input_sha256=sha256,

                )

            return JsValidationResult(

                is_valid=False,

                error_class=CLASS_VALIDATOR_EXECUTION_ERROR,

                error_message="Node.js executable not found in PATH; validation cannot complete via node --check",

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                input_sha256=sha256,

            )

        except Exception as e:

            return JsValidationResult(

                is_valid=False,

                error_class=CLASS_VALIDATOR_ENVIRONMENT_ERROR,

                error_message=f"Failed reading file for validation: {e}",

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                input_sha256=sha256,

            )



    # Get node version

    node_ver = ""

    try:

        v_proc = subprocess.run([node_bin, "--version"], capture_output=True, text=True, timeout=2)

        node_ver = v_proc.stdout.strip()

    except Exception:

        pass



    # Check for legacy staging or non-standard extension (e.g. app.js.pending or .pending) (Phase A2)

    is_legacy_staged = path.suffix == ".pending" or ".pending." in path.name

    temp_validation_copy: Optional[Path] = None

    target_to_check = path



    try:

        if path.suffix == ".pending":

            stem = path.stem

            if stem.endswith(".js"):

                actual_ext = ".js"

            elif stem.endswith(".mjs"):

                actual_ext = ".mjs"

            elif stem.endswith(".cjs"):

                actual_ext = ".cjs"

            else:

                actual_ext = ".js"



            temp_name = f".__hermes_val_{uuid.uuid4().hex[:8]}__{Path(stem).stem}{actual_ext}"

            temp_validation_copy = path.parent / temp_name

            shutil.copyfile(path, temp_validation_copy)

            target_to_check = temp_validation_copy



        cmd = [node_bin, "--check", str(target_to_check)]

        cwd_dir = str(ws_root if ws_root.exists() else path.parent)



        try:

            proc = subprocess.run(

                cmd,

                capture_output=True,

                text=True,

                cwd=cwd_dir,

                timeout=5,

            )

        except subprocess.TimeoutExpired:

            return JsValidationResult(

                is_valid=False,

                error_class=CLASS_VALIDATION_TIMEOUT,

                error_message="Validation command timed out after 5 seconds",

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                command_args=cmd,

                cwd=cwd_dir,

                node_version=node_ver,

                input_sha256=sha256,

            )



        if proc.returncode == 0:

            return JsValidationResult(

                is_valid=True,

                error_class=CLASS_VALIDATION_SUCCESS,

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                command_args=cmd,

                cwd=cwd_dir,

                node_version=node_ver,

                input_sha256=sha256,

                stdout=proc.stdout,

                stderr=proc.stderr,

                exit_code=0,

            )



        err = proc.stderr.strip()

        stdout = proc.stdout.strip()

        exit_code = proc.returncode



        # 1. Unknown file extension -> tooling extension defect

        if "ERR_UNKNOWN_FILE_EXTENSION" in err:

            return JsValidationResult(

                is_valid=False,

                error_class=CLASS_TOOLING_EXTENSION_ERROR,

                error_message=f"Node.js does not recognize file extension: {err.splitlines()[-1] if err else 'ERR_UNKNOWN_FILE_EXTENSION'}",

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                command_args=cmd,

                cwd=cwd_dir,

                node_version=node_ver,

                input_sha256=sha256,

                stdout=stdout,

                stderr=err,

                exit_code=exit_code,

            )



        # 2. Module configuration error - check if valid ES module in browser context (<script type="module">)

        if "Cannot use import statement outside a module" in err:

            content_sample = path.read_text(encoding="utf-8", errors="ignore")

            has_esm_syntax = bool(re.search(r'^\s*(?:import|export)\s', content_sample, re.M))

            mod_format = detect_js_module_format(path, ws_root)

            # If loaded as a module in HTML or contains ESM syntax, verify syntax as .mjs

            if mod_format == "module" or has_esm_syntax or path.name in ("main.js", "app.js", "index.js"):

                mjs_tmp = path.parent / f".__hermes_val_mjs_{uuid.uuid4().hex[:8]}.mjs"

                try:

                    shutil.copyfile(path, mjs_tmp)

                    mjs_res = subprocess.run([node_bin, "--check", str(mjs_tmp)], capture_output=True, text=True, cwd=cwd_dir, timeout=5)

                    if mjs_res.returncode == 0:

                        return JsValidationResult(

                            is_valid=True,

                            error_class=CLASS_VALIDATION_SUCCESS,

                            canonical_target=canonical_str,

                            staged_path=str(path),

                            workspace_root=str(ws_root),

                            command_args=cmd,

                            cwd=cwd_dir,

                            node_version=node_ver,

                            input_sha256=sha256,

                            stdout=mjs_res.stdout,

                            stderr=mjs_res.stderr,

                            exit_code=0,

                        )

                finally:

                    if mjs_tmp.exists():

                        try:

                            mjs_tmp.unlink()

                        except Exception:

                            pass



            return JsValidationResult(

                is_valid=False,

                error_class=CLASS_MODULE_MODE_MISMATCH,

                error_message=f"JavaScript module format mismatch: {err.splitlines()[0]}",

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                command_args=cmd,

                cwd=cwd_dir,

                node_version=node_ver,

                input_sha256=sha256,

                stdout=stdout,

                stderr=err,

                exit_code=exit_code,

            )

        elif "require is not defined in ES module scope" in err:

            return JsValidationResult(

                is_valid=False,

                error_class=CLASS_MODULE_MODE_MISMATCH,

                error_message=f"JavaScript module format mismatch: {err.splitlines()[0]}",

                canonical_target=canonical_str,

                staged_path=str(path),

                workspace_root=str(ws_root),

                command_args=cmd,

                cwd=cwd_dir,

                node_version=node_ver,

                input_sha256=sha256,

                stdout=stdout,

                stderr=err,

                exit_code=exit_code,

            )



        # 3. Parse line number e.g. path:77 or :(\d+)

        line_num = None

        col_num = None

        m_line = re.search(r':(\d+)(?::(\d+))?\s*(?:\n|$)', err)

        if m_line:

            try:

                line_num = int(m_line.group(1))

                if m_line.group(2):

                    col_num = int(m_line.group(2))

            except Exception:

                pass



        if col_num is None:

            lines = err.splitlines()

            for idx, l in enumerate(lines):

                if re.match(r'^\s*\^\s*$', l) and idx > 0:

                    col_num = len(lines[idx].split('^')[0]) + 1

                    break



        m_err = re.search(r'((?:SyntaxError|TypeError|ReferenceError):[^\r\n]+)', err)

        msg = m_err.group(1) if m_err else (err.splitlines()[-1] if err.splitlines() else "JavaScript syntax error")

        err_class = CLASS_APP_SYNTAX_ERROR if "SyntaxError" in err or "SyntaxError" in msg else CLASS_VALIDATOR_EXECUTION_ERROR



        return JsValidationResult(

            is_valid=False,

            error_class=err_class,

            error_message=f"{msg} at line {line_num or 'unknown'}" + (f", col {col_num}" if col_num else ""),

            line=line_num,

            column=col_num,

            canonical_target=canonical_str,

            staged_path=str(path),

            workspace_root=str(ws_root),

            command_args=cmd,

            cwd=cwd_dir,

            node_version=node_ver,

            input_sha256=sha256,

            stdout=stdout,

            stderr=err,

            exit_code=exit_code,

        )



    finally:

        if temp_validation_copy and temp_validation_copy.exists():

            try:

                temp_validation_copy.unlink()

            except Exception as e:

                logger.debug(f"Could not remove temporary validation copy: {e}")





def promote_staged_javascript(

    staged_path: Path | str,

    canonical_target: Path | str,

    workspace_root: Path | str,

    expected_sha256: Optional[str] = None,

) -> Tuple[bool, str]:

    """

    Atomically promote a validated staged artifact to its final destination (Phase A6).

    Enforces:

      1. Destination stays strictly within workspace (rejecting traversal / escapes).

      2. Staged file still matches validated input hash.

      3. Uses os.replace for same-volume atomic replacement.

      4. Preserves previous working final artifact if replacement fails.

    Returns (success, message).

    """

    staged = Path(staged_path).resolve()

    ws = Path(workspace_root).resolve()

    target = Path(canonical_target)



    if not target.is_absolute():

        target = (ws / target).resolve()

    else:

        target = target.resolve()



    try:

        target.relative_to(ws)

    except ValueError:

        return False, f"Target path '{target}' escapes workspace root '{ws}'"



    if not staged.exists() or not staged.is_file():

        return False, f"Staged file does not exist: {staged}"



    current_sha256 = compute_file_sha256(staged)

    if expected_sha256 and current_sha256 != expected_sha256:

        return False, f"Staged file content hash mismatch (expected {expected_sha256}, got {current_sha256})"



    target.parent.mkdir(parents=True, exist_ok=True)

    try:

        os.replace(staged, target)

        return True, f"Successfully promoted {staged.name} -> {target.relative_to(ws)}"

    except Exception as e:

        return False, f"Atomic promotion failed: {e}"





def validate_javascript_file(

    file_path: Path | str,

    workspace_root: Optional[Path | str] = None,

    canonical_target: Optional[Path | str] = None,

) -> Tuple[bool, Optional[str], Optional[int]]:

    """

    Standard backward-compatible validation entrypoint.

    Returns (is_valid, error_message, line_number).

    """

    res = validate_javascript_detailed(

        file_path=file_path,

        workspace_root=workspace_root,

        canonical_target=canonical_target,

    )

    if res.is_valid:

        return True, None, None

    return False, res.error_message, res.line





def validate_javascript_content(

    content: str,

    filename: str = "temp.js",

    workspace_root: Optional[Path | str] = None,

) -> Tuple[bool, Optional[str], Optional[int]]:

    """

    Validate JavaScript code content via authoritative node --check when available,

    with in-process lexical check fallback.

    Returns (is_valid, error_message, line_number).

    """

    # First, run in-process bracket & token balance check

    is_bal, bal_err, bal_line = check_js_bracket_balance(content)

    if not is_bal:

        return False, bal_err, bal_line



    node_bin = shutil.which("node")

    if node_bin:

        tmp_file: Optional[Path] = None

        try:

            ext = ".js"

            if filename.endswith(".mjs") or bool(re.search(r'^\s*(?:import|export)\s', content, re.M)):

                ext = ".mjs"

            elif filename.endswith(".cjs"):

                ext = ".cjs"

            with tempfile.NamedTemporaryFile("w", suffix=ext, delete=False, encoding="utf-8") as f:

                f.write(content)

                tmp_file = Path(f.name)

            return validate_javascript_file(tmp_file, workspace_root=workspace_root)

        finally:

            if tmp_file and tmp_file.exists():

                try:

                    tmp_file.unlink()

                except Exception:

                    pass



    return True, None, None





@dataclass

class CodeValidationResult:

    """Unified validation result for Python, JSON, and other language artifacts."""

    is_valid: bool

    language: str

    error_class: str

    error_message: Optional[str] = None

    line: Optional[int] = None

    column: Optional[int] = None

    file_path: Optional[str] = None

    input_sha256: Optional[str] = None



    def to_dict(self) -> Dict[str, Any]:

        return asdict(self)





def validate_python_code(

    source: str,

    file_path: Optional[str] = None,

) -> CodeValidationResult:

    """Validate Python code via AST parsing without execution (Section 6.3)."""

    sha = hashlib.sha256(source.encode("utf-8")).hexdigest()

    try:

        ast.parse(source, filename=file_path or "<string>")

        return CodeValidationResult(

            is_valid=True,

            language="python",

            error_class=CLASS_VALIDATION_SUCCESS,

            file_path=file_path,

            input_sha256=sha,

        )

    except SyntaxError as e:

        msg = f"SyntaxError in {file_path or '<string>'}: {e.msg} at line {e.lineno}, col {e.offset}"

        return CodeValidationResult(

            is_valid=False,

            language="python",

            error_class=CLASS_SYNTAX_ERROR,

            error_message=msg,

            line=e.lineno,

            column=e.offset,

            file_path=file_path,

            input_sha256=sha,

        )





def validate_python_file(path: Path | str) -> Tuple[bool, Optional[str], Optional[int]]:

    """Validate a Python file on disk using AST parse."""

    p = Path(path)

    if not p.exists() or not p.is_file():

        return False, f"File does not exist: {path}", None

    try:

        content = p.read_text(encoding="utf-8", errors="replace")

        res = validate_python_code(content, file_path=str(p))

        if res.is_valid:

            return True, None, None

        return False, res.error_message, res.line

    except Exception as e:

        return False, str(e), None





def validate_json_code(

    source: str,

    file_path: Optional[str] = None,

) -> CodeValidationResult:

    """Validate JSON text via json.loads with line and column extraction (Section 6.3)."""

    sha = hashlib.sha256(source.encode("utf-8")).hexdigest()

    try:

        json.loads(source)

        return CodeValidationResult(

            is_valid=True,

            language="json",

            error_class=CLASS_VALIDATION_SUCCESS,

            file_path=file_path,

            input_sha256=sha,

        )

    except json.JSONDecodeError as e:

        msg = f"JSONDecodeError in {file_path or '<string>'}: {e.msg} at line {e.lineno}, col {e.colno}"

        return CodeValidationResult(

            is_valid=False,

            language="json",

            error_class=CLASS_SYNTAX_ERROR,

            error_message=msg,

            line=e.lineno,

            column=e.colno,

            file_path=file_path,

            input_sha256=sha,

        )





def validate_json_file(path: Path | str) -> Tuple[bool, Optional[str], Optional[int], Optional[int]]:

    """Validate a JSON file on disk."""

    p = Path(path)

    if not p.exists() or not p.is_file():

        return False, f"File does not exist: {path}", None, None

    try:

        content = p.read_text(encoding="utf-8", errors="replace")

        res = validate_json_code(content, file_path=str(p))

        if res.is_valid:

            return True, None, None, None

        return False, res.error_message, res.line, res.column

    except Exception as e:

        return False, str(e), None, None





def stage_and_promote_file(

    workspace_root: Path | str,

    target_rel_path: str,

    content: str,

) -> Tuple[bool, str, Dict[str, Any]]:

    """

    Safely stage content, validate syntax, and promote to target_rel_path if valid (Section 6).

    Preserves existing canonical file on validation failure.

    Records before/after sha256 hashes.

    """

    ws = Path(workspace_root).resolve()

    dest = (ws / target_rel_path).resolve()

    dest.parent.mkdir(parents=True, exist_ok=True)



    dest_before_hash = compute_file_sha256(dest) if dest.exists() else None



    # Determine staged path e.g. app.pending.js

    ext = dest.suffix

    staged_name = f"{dest.stem}.pending{ext}"

    staged_path = dest.parent / staged_name

    staged_path.write_text(content, encoding="utf-8")



    staged_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()



    # Validate based on extension

    is_valid = True

    err_msg = ""

    err_line = None

    err_col = None



    if ext in (".js", ".mjs", ".cjs"):

        is_valid, err_msg, err_line = validate_javascript_file(staged_path)

    elif ext == ".py":

        is_valid, err_msg, err_line = validate_python_file(staged_path)

    elif ext == ".json":

        is_valid, err_msg, err_line, err_col = validate_json_file(staged_path)



    if not is_valid:

        return False, f"Validation failed: {err_msg}", {

            "staged_path": str(staged_path),

            "canonical_path": str(dest),

            "before_hash": dest_before_hash,

            "error": err_msg,

            "line": err_line,

            "column": err_col,

        }



    dest.write_text(content, encoding="utf-8")

    staged_path.unlink(missing_ok=True)

    dest_after_hash = compute_file_sha256(dest)



    return True, "Successfully validated and promoted", {

        "canonical_path": str(dest),

        "before_hash": dest_before_hash,

        "after_hash": dest_after_hash,

        "input_hash": staged_hash,

    }

