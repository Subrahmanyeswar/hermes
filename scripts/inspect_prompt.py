import json

transcript_path = r"C:\Users\SUBBU\.gemini\antigravity\brain\0053cd8a-b464-4edf-b9e4-90e766120e56\.system_generated\logs\transcript_full.jsonl"
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("type") == "USER_INPUT":
            step = data.get("step_index")
            content = data.get("content", "")
            preview = content[:100].replace("\n", " ")
            print(f"Step {step}: len={len(content)} preview={preview}")
