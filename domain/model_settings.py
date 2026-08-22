from dataclasses import dataclass

@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    widget: str
    default: str
    min_value: int
    max_value: int
    step: float | int
    help: str
    providers: tuple[str, ...] = ("openrouter", "ollama")


SETTINGS = (
    Setting("temperature", "Temperature", "slider", 0.3, 0.0, 2.0, 0.1,
                  "Higher is more creative, lower is more focused."),
    Setting("max_tokens", "Max Tokens", "number", 1000, 100, 10000, 100,
                  "Upper bound on the length of the reply"),
    Setting("top_p", "Top P", "slider", 1.0, 0.0, 1.0, 0.1,
                  "Nucleus sampling. Leave at 1.0 unless you know you want it."),
)


def defaults(provider: str) -> dict:
    return {
        s.key: s.default for s in SETTINGS if provider in s.providers
    }