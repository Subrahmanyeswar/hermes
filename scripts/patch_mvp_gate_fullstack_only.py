from pathlib import Path

target_file = Path(r"C:\Users\SUBBU\Downloads\hermes\core\agent_loop\mvp_gate.py")
text = target_file.read_text(encoding="utf-8")

old_code = """            # 6. Responsibility Contract Validation (Section 9.1)
            try:
                from core.responsibility_contract import ResponsibilityContractEvaluator
                resp_rep = ResponsibilityContractEvaluator.evaluate_workspace(ws)
                if not resp_rep.valid:
                    for u in resp_rep.unmet_responsibilities:
                        missing.append(f"Unmet responsibility: {u}")
            except Exception as e:
                logger.debug(f"WebsiteMvpGate: responsibility validation notice: {e}")"""

new_code = """            # 6. Responsibility Contract Validation (Section 9.1) for full-stack applications
            has_backend = (ws / "main.py").exists() or (ws / "app.py").exists() or (ws / "server.py").exists()
            if has_backend:
                try:
                    from core.responsibility_contract import ResponsibilityContractEvaluator
                    resp_rep = ResponsibilityContractEvaluator.evaluate_workspace(ws)
                    if not resp_rep.valid:
                        for u in resp_rep.unmet_responsibilities:
                            missing.append(f"Unmet responsibility: {u}")
                except Exception as e:
                    logger.debug(f"WebsiteMvpGate: responsibility validation notice: {e}")"""

if old_code in text:
    new_text = text.replace(old_code, new_code, 1)
    target_file.write_text(new_text, encoding="utf-8")
    print("Patched mvp_gate.py to restrict responsibility contract to full-stack projects")
else:
    print("Target not found")
