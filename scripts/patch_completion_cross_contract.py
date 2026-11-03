from pathlib import Path

p = Path("core/agent_loop/completion.py")
content = p.read_text(encoding="utf-8").replace("\r\n", "\n")

target = '''        # 4a. Deterministic Cross-File Contract Alignment Verification (Contracts first)
        if ws_root and ws_root.exists():
            from core.alignment_verifier import verify_project_alignment'''

replacement = '''        # 4a. Deterministic Cross-File Contract Alignment Verification (Contracts first)
        if ws_root and ws_root.exists():
            from core.cross_file_contract import CrossFileContractValidator
            cross_report = CrossFileContractValidator.validate_workspace(ws_root)
            if not cross_report.valid:
                err_msgs = (
                    cross_report.endpoint_mismatches
                    + cross_report.html_asset_mismatches
                    + cross_report.dom_id_mismatches
                    + cross_report.database_mismatches
                    + cross_report.startup_mismatches
                )
                if err_msgs:
                    return (
                        False,
                        f"Completion rejected: Cross-file contract validation failed ({len(err_msgs)} error(s)): {cross_report.summary}",
                        err_msgs,
                    )

            from core.alignment_verifier import verify_project_alignment'''

assert target in content, "Could not find target in completion.py"
content = content.replace(target, replacement, 1)
p.write_text(content, encoding="utf-8")
print("Successfully patched completion.py with CrossFileContractValidator check")
