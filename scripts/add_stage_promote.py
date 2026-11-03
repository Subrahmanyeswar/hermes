from pathlib import Path

p = Path("core/js_syntax_validator.py")
content = p.read_text(encoding="utf-8").replace("\r\n", "\n")

func = '''

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
        # Failed validation preserves staged content AND preserves previous canonical artifact
        return False, f"Validation failed: {err_msg}", {
            "staged_path": str(staged_path),
            "canonical_path": str(dest),
            "before_hash": dest_before_hash,
            "error": err_msg,
            "line": err_line,
            "column": err_col,
        }

    # Successful validation promotes staged to canonical
    dest.write_text(content, encoding="utf-8")
    staged_path.unlink(missing_ok=True)
    dest_after_hash = compute_file_sha256(dest)

    return True, "Successfully validated and promoted", {
        "canonical_path": str(dest),
        "before_hash": dest_before_hash,
        "after_hash": dest_after_hash,
        "input_hash": staged_hash,
    }
'''

if "def stage_and_promote_file(" not in content:
    content += func
    p.write_text(content, encoding="utf-8")
    print("Added stage_and_promote_file to core/js_syntax_validator.py")
else:
    print("stage_and_promote_file already exists")
