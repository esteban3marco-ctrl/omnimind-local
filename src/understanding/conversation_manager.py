"""Multi-turn conversation state management."""
from collections import deque

class ConversationManager:
    def __init__(self, max_turns: int = 10):
        self.history = deque(maxlen=max_turns)

    def add_turn(self, role: str, content: str):
        self.history.append({"role": role, "content": content})

    def get_history(self) -> list:
        return list(self.history)

    def clear(self):
        self.history.clear()
