from pathlib import Path
import sys


GAMES_DIR = Path(__file__).resolve().parent
PROJECT_DIR = GAMES_DIR.parent
SAM2_REPO_DIR = PROJECT_DIR / "sam2"

BACKGROUND_IMAGE = GAMES_DIR / "background_stage.png"
RANKING_FILE = GAMES_DIR / "ranking.json"

SAM2_CONFIG = SAM2_REPO_DIR / "sam2" / "configs" / "sam2.1" / "sam2.1_hiera_l.yaml"
SAM2_CHECKPOINT = SAM2_REPO_DIR / "checkpoints" / "sam2.1_hiera_large.pt"


def ensure_sam2_import_path():
    sam2_path = str(SAM2_REPO_DIR)
    if sam2_path not in sys.path:
        sys.path.insert(0, sam2_path)
