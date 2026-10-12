import shutil
import sys
from pathlib import Path


def seed(source: Path, user_md: Path, state_dir: Path) -> None:
    marker = state_dir / "bootstrap-decided"
    if marker.exists():
        return
    state_dir.mkdir(parents=True, exist_ok=True)
    if source.exists() and not user_md.exists():
        shutil.copyfile(source, state_dir / "BOOTSTRAP.md")
    marker.touch()


def main() -> int:
    source, user_md, state_dir = (Path(arg) for arg in sys.argv[1:4])
    seed(source, user_md, state_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
