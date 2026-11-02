"""What every published task must be, checked on each push and pull request.

- The layout: everything outside this repo's own files is a task folder,
  ``datasets/<name>/<task>/``, with a ``task.toml``.
- No secrets: environment values are ``${VAR}`` templates, and no file holds
  anything shaped like a key.
- Prebuilt images only, all on ``ghcr.io/amoh-ai`` and pinned by digest
  (``docker_image``, compose ``image:``, the Dockerfile's ``FROM``); nothing
  is built where it runs.

    uv run --no-project --with pyyaml python .github/check_tasks.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OWN = {"README.md", "LICENSE", "NOTICE", ".gitattributes"}
IMAGE = re.compile(r"^ghcr\.io/amoh-ai/[a-z0-9._-]+:[\w.-]+@sha256:[0-9a-f]{64}$")
TEMPLATE = re.compile(r"^\$\{[A-Z][A-Z0-9_]*(:-[^${}]*)?\}$")
SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL")
SECRETS = {
    "an OpenAI key": r"\bsk-(proj-)?[A-Za-z0-9_-]{20,}",
    "an ElevenLabs key": r"\bsk_[0-9a-f]{40,}",
    "an AWS access key": r"\b(AKIA|ASIA)[0-9A-Z]{16}\b",
    "a Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "a GitHub token": r"\b(ghp|gho|ghs|ghu)_[A-Za-z0-9]{36}\b|\bgithub_pat_\w{40,}",
    "a Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "a private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
}


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return out.splitlines()


def env_problems(where: str, table: dict) -> list[str]:
    problems = []
    for name, value in (table.get("env") or {}).items():
        if not isinstance(value, str):
            problems.append(f"{where}: env {name} is not a string")
        elif SECRET_NAME.search(name) and not TEMPLATE.match(value):
            problems.append(f"{where}: env {name} is not a ${{VAR}} template")
    return problems


def image_problems(where: str, image: str) -> list[str]:
    if IMAGE.match(image):
        return []
    return [f"{where}: {image} is not ghcr.io/amoh-ai/<name>:<tag>@sha256:<digest>"]


def task_problems(task: Path) -> list[str]:
    where = task.relative_to(ROOT).as_posix()
    problems = []
    for config in ("task.toml", "voice.toml"):
        if not (task / config).is_file():
            continue
        data = tomllib.loads((task / config).read_text(encoding="utf-8"))
        environment = data.get("environment") or {}
        problems += env_problems(f"{where}/{config}", environment)
        if config == "task.toml":
            if not environment.get("docker_image"):
                problems.append(f"{where}/task.toml: no docker_image (a prebuilt main)")
            else:
                problems += image_problems(f"{where}/task.toml", environment["docker_image"])
    compose = task / "environment" / "docker-compose.yaml"
    if compose.is_file():
        services = (yaml.safe_load(compose.read_text(encoding="utf-8")) or {}).get(
            "services"
        ) or {}
        for name, service in services.items():
            if "build" in service:
                problems.append(f"{where}: compose service {name} is built, not pulled")
            if "image" in service:
                problems += image_problems(f"{where} compose {name}", service["image"])
    dockerfile = task / "environment" / "Dockerfile"
    if dockerfile.is_file():
        for image in re.findall(r"(?im)^FROM\s+(\S+)", dockerfile.read_text(encoding="utf-8")):
            problems += image_problems(f"{where}/environment/Dockerfile", image)
    return problems


def main() -> int:
    files = tracked()
    problems, tasks = [], set()
    for path in files:
        parts = path.split("/")
        if path in OWN or parts[0] == ".github":
            continue
        if parts[0] != "datasets" or len(parts) < 4:
            problems.append(f"{path}: outside a task folder (datasets/<name>/<task>/)")
            continue
        tasks.add("/".join(parts[:3]))
    for task in sorted(tasks):
        if not (ROOT / task / "task.toml").is_file():
            problems.append(f"{task}: no task.toml")
            continue
        problems += task_problems(ROOT / task)
    for path in files:
        text = (ROOT / path).read_bytes().decode("utf-8", errors="replace")
        for what, pattern in SECRETS.items():
            if re.search(pattern, text):
                problems.append(f"{path}: holds what looks like {what}")
    for problem in problems:
        print(problem)
    print(f"{len(tasks)} tasks, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
