"""Tests for bounded non-executable terminal input helpers."""

from project_catalog_agent.demo.input import (
    prompt_bounded_text,
    prompt_menu_choice,
    prompt_yes_no,
)


def test_invalid_menu_input_reprompts_until_valid() -> None:
    values = iter(["invalid", "2"])
    output: list[str] = []

    result = prompt_menu_choice(
        "Choice: ",
        {"1": "one", "2": "two"},
        input_reader=lambda _prompt: next(values),
        output_writer=output.append,
    )

    assert result == "2"
    assert output == ["Invalid selection. Please enter one listed option."]


def test_yes_no_and_bounded_text_handle_validation_and_cancellation() -> None:
    answers = iter(["maybe", "yes"])
    output: list[str] = []
    assert (
        prompt_yes_no(
            "Continue? ",
            input_reader=lambda _prompt: next(answers),
            output_writer=output.append,
        )
        is True
    )
    assert output == ["Please enter y, n, or q to cancel."]
    assert (
        prompt_bounded_text(
            "Value: ",
            max_length=5,
            input_reader=lambda _prompt: "cancel",
        )
        is None
    )
