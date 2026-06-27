import os
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s]: %(message)s")

files_to_create = {
    # ====== CI/CD (full workflow) ======
    ".github/workflows/ci-cd.yml": """\
name: CI/CD – per-service test, build & push

on:
    push:
        branches: [main]
    pull_request:
        branches: [main]

jobs:
    # -----------------------------------------------
    # 1. Lint and format the entire repository
    # -----------------------------------------------
    lint:
        runs-on: ubuntu-latest
        steps:
            - uses: actions/checkout@v4
            - uses: astral-sh/setup-uv@v5
            - name: Install dependencies
                run: uv sync --frozen
            - name: Lint with Ruff
                run: uv run ruff check .
            - name: Check formatting with Ruff
                run: uv run ruff format --check .

    # -----------------------------------------------
    # 2. Detect which services changed
    # -----------------------------------------------
    detect-changes:
        runs-on: ubuntu-latest
        outputs:
            chainlit-ui: ${{ steps.filter.outputs.chainlit-ui }}
            api: ${{ steps.filter.outputs.api }}
            orchestrator: ${{ steps.filter.outputs.orchestrator }}
            litellm-gateway: ${{ steps.filter.outputs.litellm-gateway }}
            shared: ${{ steps.filter.outputs.shared }}
        steps:
            - uses: actions/checkout@v4
            - uses: dorny/paths-filter@v3
                id: filter
                with:
                    filters: |
                        chainlit-ui:
                            - 'services/chainlit-ui/**'
                            - 'services/shared/**'
                        api:
                            - 'services/api/**'
                            - 'services/shared/**'
                        orchestrator:
                            - 'services/orchestrator/**'
                            - 'services/shared/**'
                        litellm-gateway:
                            - 'services/litellm-gateway/**'
                            - 'services/shared/**'
                        shared:
                            - 'services/shared/**'

    # -----------------------------------------------
    # 3. Test services that changed, or all services when shared code changes
    # -----------------------------------------------
    test:
        needs: [lint, detect-changes]
        runs-on: ubuntu-latest
        strategy:
            matrix:
                service: [chainlit-ui, api, orchestrator, litellm-gateway]
        if: ${{ needs.detect-changes.outputs.shared == 'true' || needs.detect-changes.outputs[matrix.service] == 'true' }}
        steps:
            - uses: actions/checkout@v4
            - uses: astral-sh/setup-uv@v5
            - name: Install dependencies for ${{ matrix.service }} (incl. dev)
                run: |
                    cd services/${{ matrix.service }}
                    uv sync --frozen --dev
            - name: Run unit tests (parallel, random, with coverage)
                run: |
                    cd services/${{ matrix.service }}
                    uv run pytest tests/

    # -----------------------------------------------
    # 4. Build Docker image artifact (main only)
    # -----------------------------------------------
    build:
        needs: [lint, detect-changes, test]
        runs-on: ubuntu-latest
        if: ${{ github.ref == 'refs/heads/main' && (needs.detect-changes.outputs.shared == 'true' || needs.detect-changes.outputs[matrix.service] == 'true') }}
        strategy:
            matrix:
                service: [chainlit-ui, api, orchestrator, litellm-gateway]
        steps:
            - uses: actions/checkout@v4
            - uses: docker/setup-buildx-action@v3
            - name: Build Docker image artifact
                run: |
                    docker buildx build \
                        --file ./services/${{ matrix.service }}/Dockerfile \
                        --tag ${{ secrets.DOCKER_USERNAME }}/graphagentkit-${{ matrix.service }}:${{ github.sha }} \
                        --tag ${{ secrets.DOCKER_USERNAME }}/graphagentkit-${{ matrix.service }}:latest \
                        --output type=docker,dest=/tmp/${{ matrix.service }}.tar \
                        .
            - uses: actions/upload-artifact@v4
                with:
                    name: image-${{ matrix.service }}
                    path: /tmp/${{ matrix.service }}.tar

    # -----------------------------------------------
    # 5. Deploy Docker image to Docker Hub (main only)
    # -----------------------------------------------
    deploy:
        needs: [lint, detect-changes, build]
        runs-on: ubuntu-latest
        if: ${{ github.ref == 'refs/heads/main' && (needs.detect-changes.outputs.shared == 'true' || needs.detect-changes.outputs[matrix.service] == 'true') }}
        strategy:
            matrix:
                service: [chainlit-ui, api, orchestrator, litellm-gateway]
        steps:
            - uses: actions/download-artifact@v4
                with:
                    name: image-${{ matrix.service }}
                    path: /tmp
            - name: Load image into Docker
                run: docker load --input /tmp/${{ matrix.service }}.tar
            - uses: docker/login-action@v3
                with:
                    username: ${{ secrets.DOCKER_USERNAME }}
                    password: ${{ secrets.DOCKER_PASSWORD }}
            - name: Push Docker image
                run: |
                    docker push ${{ secrets.DOCKER_USERNAME }}/graphagentkit-${{ matrix.service }}:${{ github.sha }}
                    docker push ${{ secrets.DOCKER_USERNAME }}/graphagentkit-${{ matrix.service }}:latest
""",
    # ====== Root config ======
    "pyproject.toml": """\
[tool.uv.workspace]
members = ["services/*"]

[project]
name = "graphagentkit"
version = "0.1.0"
description = "Agentic system with LangGraph, LiteLLM, and sub-agents"
requires-python = ">=3.11"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "C90"]   # C90 = mccabe complexity

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.bandit]
exclude_dirs = ["tests"]
""",
    "ruff.toml": "# Ruff configuration is in pyproject.toml\n",
    ".gitignore": """\
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Environment
.env
.env.*

# IDE
.idea/
.vscode/

# Docker
*.log
volumes/

# OS
.DS_Store
""",
    ".dockerignore": """\
# Git
.git
.gitignore
.gitattributes

# CI/CD
.github

# Python
__pycache__
*.pyc
.venv
*.egg-info
.pytest_cache
.mypy_cache
.ruff_cache

# Environment
.env
.env.*

# Editor
.idea
.vscode

# Docker
Dockerfile
.dockerignore
docker-compose.yml

# Misc
*.md
LICENSE
""",
    ".pre-commit-config.yaml": """\
repos:
  # ---- Basic file checks & best practices ----
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
      - id: detect-private-key
      - id: check-ast

  # ---- Linting & formatting ----
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.1
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  # ---- Security ----
  - repo: https://github.com/PyCQA/bandit
    rev: 1.7.8
    hooks:
      - id: bandit
        args: ["-c", "pyproject.toml"]
        additional_dependencies: [".[toml]"]

  # ---- Code complexity ----
  - repo: https://github.com/PyCQA/mccabe
    rev: 0.7.0
    hooks:
      - id: mccabe
        args: ["--max-complexity", "10"]

  # ---- Custom: ensure tests accompany source changes ----
  - repo: local
    hooks:
      - id: check-tests
        name: Check unit tests for changed code
        entry: python scripts/check_tests.py
        language: python
        files: 'services/.*\\.py$'
        stages: [commit]
""",
    ".env.example": """\
# LangFuse (self-hosted)
LANGFUSE_HOST=http://localhost:3000
LANGFUSE_PUBLIC_KEY=pk-xxxx
LANGFUSE_SECRET_KEY=sk-xxxx

# Ollama
OLLAMA_API_BASE=http://ollama:11434

# LangFuse secrets
LANGFUSE_NEXTAUTH_SECRET=change-me-please
LANGFUSE_SALT=change-me-please
""",
    "docker-compose.yml": None,
    "README.md": "# GraphAgentKit\n\nAgentic system playground.\n",
    "uv.lock": "",
    # ====== Custom pre‑commit script ======
    "scripts/check_tests.py": """\
import sys
import subprocess
from pathlib import Path

def get_staged_files():
    \"\"\"Return list of staged file paths.\"\"\"
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Error: Could not get staged files.")
        sys.exit(1)
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]

def main():
    staged = get_staged_files()
    if not staged:
        print("No staged files to check.")
        return 0

    source_files = [
        f for f in staged
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
        service_dir = Path(src).parent
        test_dir = service_dir / "tests"
        has_staged_test = any(
            staged_file.startswith(str(test_dir)) for staged_file in staged
        )
        if not has_staged_test:
            errors.append(
                f"  - {src}: no corresponding test file staged in {test_dir}"
            )

    if errors:
        print("❌ Commit rejected: The following changed source files lack unit tests:")
        for e in errors:
            print(e)
        print("\\nPlease add or update tests in the service's tests/ directory and stage them.")
        return 1

    print("✅ All changed source files have corresponding test files staged.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
""",
    # ====== Shared library ======
    "services/shared/pyproject.toml": """\
[project]
name = "agentic-shared"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = [
    "pytest>=8.3.4",
    "pytest-mock>=3.14.0",
    "pytest-xdist>=3.6.1",
    "pytest-cov>=6.0.0",
    "pytest-instafail>=0.5.0",
    "pytest-randomly>=3.16.0",
]

[tool.pytest.ini_options]
addopts = [
    "--randomly-seed=last",
    "--instafail",
    "-n", "auto",
    "--cov=.",
    "--cov-report=term-missing"
]
""",
    "services/shared/agentic_shared/__init__.py": "",
    "services/shared/agentic_shared/models.py": "# Shared Pydantic models\n",
    "services/shared/agentic_shared/utils.py": "# Common utilities\n",
    "services/shared/tests/__init__.py": "",
    "services/shared/tests/test_shared.py": "# Tests for shared library\n",
    # ====== Service: chainlit-ui ======
    "services/chainlit-ui/pyproject.toml": """\
[project]
name = "agentic-chainlit-ui"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "chainlit",
    "agentic-shared",
]

[dependency-groups]
dev = [
    "pytest>=8.3.4",
    "pytest-mock>=3.14.0",
    "pytest-xdist>=3.6.1",
    "pytest-cov>=6.0.0",
    "pytest-instafail>=0.5.0",
    "pytest-randomly>=3.16.0",
]

[tool.pytest.ini_options]
addopts = [
    "--randomly-seed=last",
    "--instafail",
    "-n", "auto",
    "--cov=.",
    "--cov-report=term-missing"
]
""",
    "services/chainlit-ui/app.py": "# Chainlit entrypoint\n",
    "services/chainlit-ui/Dockerfile": None,
    "services/chainlit-ui/tests/__init__.py": "",
    "services/chainlit-ui/tests/test_app.py": "# Unit tests for Chainlit UI\n",
    # ====== Service: api ======
    "services/api/pyproject.toml": """\
[project]
name = "agentic-api"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi",
    "uvicorn",
    "httpx",
    "langfuse",
    "agentic-shared",
]

[dependency-groups]
dev = [
    "pytest>=8.3.4",
    "pytest-mock>=3.14.0",
    "pytest-xdist>=3.6.1",
    "pytest-cov>=6.0.0",
    "pytest-instafail>=0.5.0",
    "pytest-randomly>=3.16.0",
]

[tool.pytest.ini_options]
addopts = [
    "--randomly-seed=last",
    "--instafail",
    "-n", "auto",
    "--cov=.",
    "--cov-report=term-missing"
]
""",
    "services/api/main.py": "# FastAPI API service\n",
    "services/api/Dockerfile": None,
    "services/api/tests/__init__.py": "",
    "services/api/tests/test_main.py": "# Unit tests for API service\n",
    # ====== Service: orchestrator ======
    "services/orchestrator/pyproject.toml": """\
[project]
name = "agentic-orchestrator"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "langgraph",
    "langchain",
    "langchain-community",
    "fastapi",
    "uvicorn",
    "httpx",
    "langfuse",
    "agentic-shared",
]

[dependency-groups]
dev = [
    "pytest>=8.3.4",
    "pytest-mock>=3.14.0",
    "pytest-xdist>=3.6.1",
    "pytest-cov>=6.0.0",
    "pytest-instafail>=0.5.0",
    "pytest-randomly>=3.16.0",
]

[tool.pytest.ini_options]
addopts = [
    "--randomly-seed=last",
    "--instafail",
    "-n", "auto",
    "--cov=.",
    "--cov-report=term-missing"
]
""",
    "services/orchestrator/graph.py": "# LangGraph state machine\n",
    "services/orchestrator/api.py": "# FastAPI wrapper for graph\n",
    "services/orchestrator/Dockerfile": None,
    "services/orchestrator/tests/__init__.py": "",
    "services/orchestrator/tests/test_graph.py": "# Unit tests for orchestrator graph\n",
    "services/orchestrator/tests/test_api.py": "# Integration tests for orchestrator API\n",
    # ====== Service: litellm-gateway ======
    "services/litellm-gateway/pyproject.toml": """\
[project]
name = "agentic-litellm-gateway"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "litellm[proxy]",
    "langchain",
    "langchain-community",
    "beautifulsoup4",
    "langfuse",
    "agentic-shared",
]

[dependency-groups]
dev = [
    "pytest>=8.3.4",
    "pytest-mock>=3.14.0",
    "pytest-xdist>=3.6.1",
    "pytest-cov>=6.0.0",
    "pytest-instafail>=0.5.0",
    "pytest-randomly>=3.16.0",
]

[tool.pytest.ini_options]
addopts = [
    "--randomly-seed=last",
    "--instafail",
    "-n", "auto",
    "--cov=.",
    "--cov-report=term-missing"
]
""",
    "services/litellm-gateway/config.yaml": "# LiteLLM gateway model list\n",
    "services/litellm-gateway/adapters/__init__.py": "",
    "services/litellm-gateway/adapters/research.py": "",
    "services/litellm-gateway/adapters/scraper.py": "",
    "services/litellm-gateway/adapters/writer.py": "",
    "services/litellm-gateway/adapters/critic.py": "",
    "services/litellm-gateway/agents/__init__.py": "",
    "services/litellm-gateway/agents/research_agent.py": "",
    "services/litellm-gateway/agents/scraper_agent.py": "",
    "services/litellm-gateway/agents/writer_agent.py": "",
    "services/litellm-gateway/agents/critic_agent.py": "",
    "services/litellm-gateway/main.py": "# LiteLLM gateway startup script\n",
    "services/litellm-gateway/Dockerfile": None,
    "services/litellm-gateway/tests/__init__.py": "",
    "services/litellm-gateway/tests/test_adapters.py": "# Unit tests for adapters\n",
    "services/litellm-gateway/tests/test_agents.py": "# Unit tests for sub-agents\n",
}

# --- Create all directories and files ---
for filepath, content in files_to_create.items():
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        logging.info(f"Already exists, skipping: {filepath}")
        continue

    with open(path, "w", encoding="utf-8") as f:
        f.write(content if content is not None else "")
    logging.info(f"Created: {filepath}")

logging.info("✅ Repository skeleton created successfully!")
