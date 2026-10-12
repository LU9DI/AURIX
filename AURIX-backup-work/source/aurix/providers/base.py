from typing import Protocol


class Provider(Protocol):
    def generate(self, prompt: str, *, system: str = "") -> str:
        """Generate a text response; implementations must apply request timeouts."""
        ...
