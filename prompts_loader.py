from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def parse_prompt_file(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8").strip()
    if not text.startswith("---\n"):
        raise ValueError(f"Invalid prompt file: {path.name} frontmatter is missing")

    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"Invalid prompt file: {path.name} has invalid frontmatter")

    raw_meta = parts[1].strip().splitlines()
    body = parts[2].strip()

    meta: dict[str, str] = {}
    for line in raw_meta:
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    return meta, body


def load_prompts() -> tuple[dict[str, dict[str, str]], str]:
    prompts: dict[str, dict[str, str]] = {}
    default_key: str | None = None

    for path in sorted(PROMPTS_DIR.glob("*.md")):
        meta, body = parse_prompt_file(path)

        key = meta["key"]
        name = meta["name"]
        description = meta["description"]
        is_default = meta.get("default", "false").lower() == "true"

        if key in prompts:
            raise ValueError(f"Duplicate prompt key: {key}")

        prompts[key] = {
            "name": name,
            "description": description,
            "system": body,
        }

        if is_default:
            if default_key is not None:
                raise ValueError(f"Multiple default prompts: {default_key} and {key}")
            default_key = key

    if not prompts:
        raise ValueError("No prompts found")

    if default_key is None:
        raise ValueError("No default prompt found")

    return prompts, default_key


PROMPTS, DEFAULT_PROMPT = load_prompts()
