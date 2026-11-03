from pathlib import Path

target_file = Path(r"C:\Users\SUBBU\Downloads\hermes\core\agent_loop\mvp_gate.py")
text = target_file.read_text(encoding="utf-8")

target = """        # 5. Cross-artifact structural integration check
        if len(missing) == 0:
            try:
                from core.integration_validator import CrossArtifactValidator
                rep = CrossArtifactValidator.validate_web_integration(ws)
                if not rep.valid:
                    for iss in rep.issues:
                        missing.append(f"DOM mismatch: {iss}")
            except Exception as e:
                logger.debug(f"WebsiteMvpGate: integration validation notice: {e}")

        return len(missing) == 0, missing"""

replacement = """        # 5. Cross-artifact structural integration check
        if len(missing) == 0:
            try:
                from core.integration_validator import CrossArtifactValidator
                rep = CrossArtifactValidator.validate_web_integration(ws)
                if not rep.valid:
                    for iss in rep.issues:
                        missing.append(f"DOM mismatch: {iss}")
            except Exception as e:
                logger.debug(f"WebsiteMvpGate: integration validation notice: {e}")

            # 6. Responsibility Contract Validation (Section 9.1)
            try:
                from core.responsibility_contract import ResponsibilityContractEvaluator
                resp_rep = ResponsibilityContractEvaluator.evaluate_workspace(ws)
                if not resp_rep.valid:
                    for u in resp_rep.unmet_responsibilities:
                        missing.append(f"Unmet responsibility: {u}")
            except Exception as e:
                logger.debug(f"WebsiteMvpGate: responsibility validation notice: {e}")

        return len(missing) == 0, missing"""

if target in text:
    new_text = text.replace(target, replacement, 1)
    target_file.write_text(new_text, encoding="utf-8")
    print("Updated mvp_gate.py successfully")
else:
    # Try normalizing line endings
    norm_text = text.replace("\r\n", "\n")
    norm_target = target.replace("\r\n", "\n")
    norm_repl = replacement.replace("\r\n", "\n")
    if norm_target in norm_text:
        new_text = norm_text.replace(norm_target, norm_repl, 1)
        target_file.write_text(new_text, encoding="utf-8")
        print("Updated mvp_gate.py successfully (normalized)")
    else:
        print("Target not found in mvp_gate.py")
