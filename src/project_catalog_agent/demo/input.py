"""Reusable bounded terminal input helpers for the demo application."""

from collections.abc import Callable, Mapping

InputReader = Callable[[str], str]
OutputWriter = Callable[[str], None]


def prompt_menu_choice(
    prompt: str,
    choices: Mapping[str, str],
    *,
    input_reader: InputReader = input,
    output_writer: OutputWriter = print,
) -> str | None:
    """Read a listed choice, supporting safe cancellation without evaluation."""
    while True:
        try:
            value = input_reader(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            output_writer("Input cancelled.")
            return None
        if value.casefold() in {"q", "cancel"}:
            return None
        if value in choices:
            return value
        output_writer("Invalid selection. Please enter one listed option.")


def prompt_yes_no(
    prompt: str,
    *,
    input_reader: InputReader = input,
    output_writer: OutputWriter = print,
) -> bool | None:
    """Return true, false, or cancellation for a bounded yes/no prompt."""
    while True:
        try:
            value = input_reader(prompt).strip().casefold()
        except (EOFError, KeyboardInterrupt):
            output_writer("Input cancelled.")
            return None
        if value in {"", "n", "no"}:
            return False
        if value in {"y", "yes"}:
            return True
        if value in {"q", "cancel"}:
            return None
        output_writer("Please enter y, n, or q to cancel.")


def prompt_bounded_text(
    prompt: str,
    *,
    max_length: int,
    allow_empty: bool = False,
    input_reader: InputReader = input,
    output_writer: OutputWriter = print,
) -> str | None:
    """Read non-executable text with a strict character limit."""
    while True:
        try:
            value = input_reader(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            output_writer("Input cancelled.")
            return None
        if value.casefold() in {"q", "cancel"}:
            return None
        if not value and not allow_empty:
            output_writer("A value is required.")
            continue
        if len(value) > max_length:
            output_writer(f"Input must contain at most {max_length} characters.")
            continue
        return value


def prompt_optional_note(
    prompt: str,
    *,
    input_reader: InputReader = input,
    output_writer: OutputWriter = print,
) -> str | None:
    """Read an optional review note limited to 1,000 characters."""
    return prompt_bounded_text(
        prompt,
        max_length=1_000,
        allow_empty=True,
        input_reader=input_reader,
        output_writer=output_writer,
    )
