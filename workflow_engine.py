import json
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Callable, Any

class EventBus:
    def __init__(self):
        self.events = []

    def publish(self, event_name: str, data: Dict[str, Any]):
        self.events.append((event_name, data))

    def get_events(self):
        return self.events

class Step(ABC):
    def __init__(self, name: str, action: Callable[[], bool]):
        self.name = name
        self.action = action

    @abstractmethod
    def execute(self) -> bool:
        pass

class ConditionalStep(Step):
    def __init__(self, name, action, condition: Callable[[], bool]):
        super().__init__(name, action)
        self.condition = condition

    def execute(self) -> bool:
        if self.condition():
            return self.action()
        return False

class WorkflowEngine:
    def __init__(self, steps: List[Step], checkpoint_dir: str = "checkpoints"):
        self.steps = steps
        self.current_step_index = 0
        self.checkpoint_dir = checkpoint_dir
        self.event_bus = EventBus()
        if not os.path.exists(checkpoint_dir):
            os.makedirs(checkpoint_dir)

    def save_checkpoint(self, state: Dict[str, Any]):
        with open(os.path.join(self.checkpoint_dir, f"checkpoint_{self.current_step_index}.json"), "w") as f:
            json.dump(state, f)

    def load_checkpoint(self, step_index: int) -> Dict[str, Any]:
        try:
            with open(os.path.join(self.checkpoint_dir, f"checkpoint_{▭step_index}.json")) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def execute_step(self, step: Step) -> bool:
        result = step.execute()
        self.event_bus.publish("step_execution", {"step": step.name, "success": result})
        return result

    def execute(self):
        while self.current_step_index < len(self.steps):
            step = self.steps[self.current_step_index]
            current_state = self.load_checkpoint(self.current_step_index)
            success = self.execute_step(step)
            if not success:
                if self.current_step_index > 0:
                    prev_state = self.load_checkpoint(self.current_step_index - 1)
                    self.apply_state(prev_state)
                else:
                    print("Cannot rollback: no previous checkpoint.")
                    break
            else:
                self.save_checkpoint(current_state)
            self.current_step_index += 1

    def apply_state(self, state: Dict[str, Any]):
        pass

if __name__ == "__main__":
    def sample_action():
        print("Executing sample action")
        return True

    def sample_condition():
        return True

    step1 = Step("Step 1", sample_action)
    step2 = ConditionalStep("Step 2", sample_action, sample_condition)

    engine = WorkflowEngine([step1, step2])
    engine.execute()