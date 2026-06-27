import sys
import subprocess
from pathlib import Path


def get_staged_files() -> list[str]:
    """Return list of staged file paths.
    Uses 'git diff --cached --name-only' to get the list of staged files.
    Returns:
        List of staged file paths as strings.
    """
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("Error: Could not get staged files.")
        sys.exit(1)
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def main() -> int:
    staged = get_staged_files()
    if not staged:
        print("No staged files to check.")
        return 0

    # Filter for Python files not in tests/ and not __init__.py
    source_files = [
        f
        for f in staged
        if f.endswith(".py")
        and "/tests/" not in f
        and not f.endswith("__init__.py")
        and f.startswith("services/")
    ]

    if not source_files:
        print("No service source files changed (excluding tests/__init__.py).")
        return 0

    errors = []
    for src in source_files:
        # Determine service directory: e.g., services/api/main.py -> services/api/
        service_dir = Path(src).parent
        test_dir = service_dir / "tests"
        # Check if any staged file lies inside test_dir
        has_staged_test = any(
            staged_file.startswith(str(test_dir)) for staged_file in staged
        )
        if not has_staged_test:
            errors.append(f"  - {src}: no corresponding test file staged in {test_dir}")

    if errors:
        print("❌ Commit rejected: The following changed source files lack unit tests:")
        for e in errors:
            print(e)
        print(
            "\nPlease add or update tests in the service's tests/ directory and stage them."
        )
        return 1

    print("✅ All changed source files have corresponding test files staged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
