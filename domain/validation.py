
def validate_input(text: str, max_length: int) -> str | None:
    if not text.strip():
        return "Please paste some text to analyse."
    if len(text) > max_length:
        return f"Input is too long (max {max_length} characters)."
    return None


def is_off_topic(reply: str, marker: str) -> bool:
    """True when the model emitted the prompt's declared off-topic marker."""
    return marker.casefold() in reply.casefold()
