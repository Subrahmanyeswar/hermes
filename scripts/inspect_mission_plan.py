import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.mission_planner import MissionPlanner
import json

prompt = "Create a small student career guidance webpage named EduPath Mini. Create index.html, styles.css, and app.js. The page should contain a simple heading, a short career-guidance section, basic styling, and a small JavaScript interaction."

planner = MissionPlanner()
# Let us check heuristic decomposition or if it calls LLM decompose
print("Testing parse_intent...")
intents = planner._parse_intent(prompt)
print("Intents count:", len(intents))
for i, item in enumerate(intents):
    print(f"{i+1}: {item}")
