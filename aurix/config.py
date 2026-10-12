import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def get_workspace() -> Path:
    return Path(os.getenv("AURIX_WORKSPACE", ".")).expanduser().resolve()


def get_max_steps() -> int:
    return max(1, min(int(os.getenv("AURIX_MAX_STEPS", "6")), 20))
