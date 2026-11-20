"""公開リポジトリのクローンを最新にする。

nro-context を取得し、その目録（catalog/catalog.yaml）にある disclosure が「公開」のリポジトリを
すべて clone または pull する。目録から外れたリポジトリのクローンは消さずに残す（手で消す）。

    python scripts/sync_repos.py /srv/nro-bot/repos
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

HUB = "https://github.com/nobeyama-radio-observatory/nro-context"


def sync(url: str, dest: Path) -> None:
    if (dest / ".git").is_dir():
        subprocess.run(["git", "-C", str(dest), "fetch", "--quiet", "--depth", "1", "origin"], check=True)
        subprocess.run(["git", "-C", str(dest), "reset", "--quiet", "--hard", "FETCH_HEAD"], check=True)
    else:
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", url, str(dest)], check=True)


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "/srv/nro-bot/repos")
    root.mkdir(parents=True, exist_ok=True)
    sync(HUB, root / "nro-context")
    catalog = yaml.safe_load((root / "nro-context" / "catalog" / "catalog.yaml").read_text(encoding="utf-8"))
    failed = 0
    for item in catalog or []:
        name, url = item.get("name"), item.get("url", "")
        if not name or name == "nro-context" or item.get("disclosure") != "公開":
            continue
        if not url.startswith("https://github.com/"):
            continue
        try:
            sync(url, root / name)
            print(f"ok {name}")
        except subprocess.CalledProcessError as e:
            failed += 1
            print(f"failed {name}: {e}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
