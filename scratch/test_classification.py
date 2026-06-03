import sys
from core.intent_classifier import IntentClassifier

classifier = IntentClassifier("skills/")
prompts = [
    "create a highend robotics website",
    "create a robotics website",
    "create a folder named demologin and create a small login page using html and css",
]

for prompt in prompts:
    result = classifier.classify(prompt)
    print(f"Prompt: {prompt!r}")
    print(f"Result: {result}")
    print("-" * 50)
