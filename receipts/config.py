"""Settings, all overridable with environment variables."""
import os
from pathlib import Path

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("RECEIPTS_MODEL", "qwen2.5:7b")
NUM_CTX = int(os.environ.get("RECEIPTS_NUM_CTX", "16384"))
CHUNK_TOKENS = int(os.environ.get("RECEIPTS_CHUNK_TOKENS", "6000"))  # leaves room in NUM_CTX for prompt + output
CHUNK_OVERLAP = 10  # lines shared by neighbouring chunks so a quote on a boundary is still whole in one of them
MAX_FILES = 300
MAX_INPUT_TOKENS = int(os.environ.get("RECEIPTS_MAX_INPUT_TOKENS", "2000000"))
ASK_CHUNKS = int(os.environ.get("RECEIPTS_ASK_CHUNKS", "4"))  # chunks read per question (best-ranked first)
EXTRACT_CHUNKS = int(os.environ.get("RECEIPTS_EXTRACT_CHUNKS", "40"))  # extract reads everything, up to this
MAX_EVIDENCE = 8
DATA_DIR = Path(os.environ.get("RECEIPTS_DATA_DIR", Path.home() / ".receipts"))


def roots() -> list[Path]:
    """Directories the server may read. RECEIPTS_ROOTS (os.pathsep-separated), else the working directory."""
    raw = os.environ.get("RECEIPTS_ROOTS")
    paths = raw.split(os.pathsep) if raw else [os.getcwd()]
    return [Path(p).expanduser().resolve() for p in paths if p]
