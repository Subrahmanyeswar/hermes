from pathlib import Path

target_file = Path(r"C:\Users\SUBBU\Downloads\hermes\core\integration_validator.py")
text = target_file.read_text(encoding="utf-8")

target = "# Convert issues to StructuredDefects"
replacement = """# 7. Cross-File Fullstack Contract Validation (Section 9.1 & 9.2)
        has_fullstack = (ws / "main.py").exists() or (ws / "app.py").exists() or (ws / "server.py").exists()
        if has_fullstack:
            try:
                from core.cross_file_contract import CrossFileContractValidator
                cf_rep = CrossFileContractValidator.validate_workspace(ws)
                if not cf_rep.valid:
                    for em in cf_rep.endpoint_mismatches:
                        issues.append(em)
                    for am in cf_rep.html_asset_mismatches:
                        issues.append(am)
                    for sm in cf_rep.startup_mismatches:
                        issues.append(sm)
            except Exception as exc:
                logger.debug(f"CrossArtifactValidator fullstack contract check notice: {exc}")

        # Convert issues to StructuredDefects"""

if target in text:
    new_text = text.replace(target, replacement, 1)
    target_file.write_text(new_text, encoding="utf-8")
    print("Updated integration_validator.py successfully")
else:
    print("Target not found in integration_validator.py")
