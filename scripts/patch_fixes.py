# scripts/patch_fixes.py
from pathlib import Path

# 1. Patch core/agent_loop/stuck_detector.py
p_stuck = Path("core/agent_loop/stuck_detector.py")
txt_stuck = p_stuck.read_text(encoding="utf-8").replace("\r\n", "\n")
target_stuck = '''        if self.mission_id and fp.mission_id and self.mission_id != fp.mission_id:
            # Automatic mission isolation if mission changed
            self.reset(fp.mission_id)'''

replacement_stuck = '''        if self.mission_id and fp.mission_id and self.mission_id != fp.mission_id:
            # Automatic mission isolation if mission changed
            self.reset(fp.mission_id)
        elif not self.mission_id and fp.mission_id:
            self.mission_id = fp.mission_id'''

assert target_stuck in txt_stuck, "Could not find target_stuck"
txt_stuck = txt_stuck.replace(target_stuck, replacement_stuck, 1)
p_stuck.write_text(txt_stuck, encoding="utf-8")
print("Patched stuck_detector.py")

# 2. Patch core/project_contract.py
p_proj = Path("core/project_contract.py")
txt_proj = p_proj.read_text(encoding="utf-8").replace("\r\n", "\n")
target_proj = '''    @classmethod
    def resolve_workspace_path('''

replacement_proj = '''    @classmethod
    def resolve(cls, workspace_root: Path | str, path_input: Path | str) -> Path:
        """Alias for resolve_workspace_path."""
        return cls.resolve_workspace_path(workspace_root, path_input)

    @classmethod
    def resolve_workspace_path('''

assert target_proj in txt_proj, "Could not find target_proj"
txt_proj = txt_proj.replace(target_proj, replacement_proj, 1)
p_proj.write_text(txt_proj, encoding="utf-8")
print("Patched project_contract.py with CanonicalPathResolver.resolve alias")

# 3. Patch core/agent_loop/completion.py for Fast Verification contract gate
p_comp = Path("core/agent_loop/completion.py")
txt_comp = p_comp.read_text(encoding="utf-8").replace("\r\n", "\n")
target_comp = '''                    for js_file in ws_root.glob("*.js"):
                        from core.js_syntax_validator import validate_javascript_file
                        j_ok, j_err, _ = validate_javascript_file(js_file)
                        if not j_ok:
                            return (
                                False,
                                f"Fast verification rejected: JavaScript syntax error in {js_file.name}: {j_err}",
                                [f"JavaScript syntax error in {js_file.name}: {j_err}"]
                            )'''

replacement_comp = '''                    for js_file in ws_root.glob("*.js"):
                        from core.js_syntax_validator import validate_javascript_file
                        j_ok, j_err, _ = validate_javascript_file(js_file)
                        if not j_ok:
                            return (
                                False,
                                f"Fast verification rejected: JavaScript syntax error in {js_file.name}: {j_err}",
                                [f"JavaScript syntax error in {js_file.name}: {j_err}"]
                            )

                    from core.cross_file_contract import CrossFileContractValidator
                    cross_rep = CrossFileContractValidator.validate_workspace(ws_root)
                    if not cross_rep.valid:
                        err_msgs = (
                            cross_rep.endpoint_mismatches
                            + cross_rep.html_asset_mismatches
                            + cross_rep.dom_id_mismatches
                            + cross_rep.database_mismatches
                            + cross_rep.startup_mismatches
                        )
                        if err_msgs:
                            return (
                                False,
                                f"Fast verification rejected: Cross-file contract validation failed ({len(err_msgs)} error(s)): {cross_rep.summary}",
                                err_msgs,
                            )'''

assert target_comp in txt_comp, "Could not find target_comp"
txt_comp = txt_comp.replace(target_comp, replacement_comp, 1)
p_comp.write_text(txt_comp, encoding="utf-8")
print("Patched completion.py for Fast Verification cross-contract gate")
