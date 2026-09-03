from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


def main() -> None:
    output_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../docs/api/openapi.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Exported OpenAPI contract to {output_path}")


if __name__ == "__main__":
    main()
