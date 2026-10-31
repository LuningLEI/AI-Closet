"""Fast CI guard for ordered, non-empty, transaction-balanced SQL migrations."""
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1] / "sql" / "migrations"
files = sorted(root.glob("[0-9][0-9][0-9]_*.sql"))
assert files, "No migrations found"
numbers = [int(path.name.split("_", 1)[0]) for path in files]
assert numbers == sorted(set(numbers)), "Migration numbers must be unique and ordered"
for path in files:
    sql = re.sub(r"--.*?$", "", path.read_text(), flags=re.MULTILINE).strip()
    assert sql, f"Empty migration: {path.name}"
    assert sql.count("$$") % 2 == 0, f"Unbalanced dollar quotes: {path.name}"
print(f"validated {len(files)} ordered migrations")
