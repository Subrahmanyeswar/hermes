# scripts/patch_batch_writer.py
from pathlib import Path

target_file = Path("tools/file_tools.py")
content = target_file.read_text(encoding="utf-8")

old_snippet = """            # 3. Commit staged files to real destinations from staging area (Section 6.6)
            for idx, (safe_dest, content, mode, rel_p) in enumerate(validated_items):
                staged_file = temp_staging_dir / f"stage_{idx}"
                safe_dest.parent.mkdir(parents=True, exist_ok=True)
                if mode == "overwrite":
                    shutil.copy2(staged_file, safe_dest)
                else:
                    staged_bytes = staged_file.read_bytes()
                    with open(safe_dest, "ab") as df:
                        df.write(staged_bytes)
                written_destinations.append(safe_dest)"""

new_snippet = """            # 3. Commit staged files to real destinations from staging area (Section 6.6)
            for idx, (safe_dest, content, mode, rel_p) in enumerate(validated_items):
                staged_file = temp_staging_dir / f"stage_{idx}"
                safe_dest.parent.mkdir(parents=True, exist_ok=True)
                staged_content = staged_file.read_text(encoding="utf-8")
                file_mode = "w" if mode == "overwrite" else "a"
                with open(safe_dest, file_mode, encoding="utf-8", newline="") as df:
                    df.write(staged_content)
                written_destinations.append(safe_dest)"""

content_norm = content.replace("\r\n", "\n")
old_norm = old_snippet.replace("\r\n", "\n")
assert old_norm in content_norm, "Old snippet not found!"

updated = content_norm.replace(old_norm, new_snippet.replace("\r\n", "\n"))
target_file.write_text(updated, encoding="utf-8")
print("Successfully patched WriteFilesBatchTool with staged_file read & open()")
