"""
HERMES Phase 4G - Independent Complexity Classification Audit
Evaluates classify_mission_complexity across reference prompts.
Outputs:
- artifacts/phase4g/complexity_predictions.json
- artifacts/phase4g/classification_confusion_matrix.json
"""

import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from core.mission_planner import classify_mission_complexity, MissionComplexity

def run_classification_audit():
    root = Path(__file__).resolve().parent.parent
    gold_file = root / "artifacts" / "phase4g" / "complexity_gold_labels.json"
    
    with open(gold_file, "r", encoding="utf-8") as f:
        samples = json.load(f)
        
    classes = ["TRIVIAL", "SIMPLE", "MEDIUM", "COMPLEX", "LARGE"]
    matrix = {c: {k: 0 for k in classes} for c in classes}
    
    predictions = []
    correct_count = 0
    total_count = len(samples)
    
    per_class_stats = {c: {"total": 0, "correct": 0} for c in classes}
    
    for item in samples:
        pid = item["id"]
        prompt = item["prompt"]
        expected = item["expected_complexity"]
        
        predicted_enum = classify_mission_complexity(prompt)
        predicted = predicted_enum.value if hasattr(predicted_enum, "value") else str(predicted_enum)
        
        is_correct = (predicted == expected)
        if is_correct:
            correct_count += 1
            per_class_stats[expected]["correct"] += 1
            
        per_class_stats[expected]["total"] += 1
        matrix[expected][predicted] += 1
        
        predictions.append({
            "id": pid,
            "prompt": prompt,
            "expected": expected,
            "predicted": predicted,
            "correct": is_correct,
            "domain": item.get("domain", "")
        })
        
    overall_accuracy = (correct_count / total_count) * 100.0
    for c in classes:
        tot = per_class_stats[c]["total"]
        cor = per_class_stats[c]["correct"]
        per_class_stats[c]["accuracy"] = round((cor / tot) * 100.0, 2) if tot > 0 else 0.0
        
    results_matrix = {
        "classes": classes,
        "confusion_matrix": matrix,
        "per_class_accuracy": per_class_stats,
        "total_samples": total_count,
        "correct_predictions": correct_count,
        "overall_accuracy_pct": round(overall_accuracy, 2)
    }
    
    preds_out = root / "artifacts" / "phase4g" / "complexity_predictions.json"
    matrix_out = root / "artifacts" / "phase4g" / "classification_confusion_matrix.json"
    
    with open(preds_out, "w", encoding="utf-8") as f:
        json.dump(predictions, f, indent=2)
        
    with open(matrix_out, "w", encoding="utf-8") as f:
        json.dump(results_matrix, f, indent=2)
        
    print(f"Classification Audit Complete:")
    print(f"Overall Accuracy: {overall_accuracy:.2f}% ({correct_count}/{total_count})")
    for c in classes:
        print(f"  {c}: {per_class_stats[c]['accuracy']}% ({per_class_stats[c]['correct']}/{per_class_stats[c]['total']})")

if __name__ == "__main__":
    run_classification_audit()
