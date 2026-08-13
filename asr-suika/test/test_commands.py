import pytest

from backend.commands import (
    canonical_command,
    canonical_commands,
    custom_recognition_forms,
)


def test_canonical_command_accepts_hiragana_and_kanji() -> None:
    assert canonical_command("すすめ") == "すすめ"
    assert canonical_command("進め") == "すすめ"
    assert canonical_command("止まれ") == "とまれ"
    assert canonical_command("右") == "みぎ"
    assert canonical_command("叩け") == "たたけ"


def test_canonical_command_ignores_spaces_and_rejects_unknown_text() -> None:
    assert canonical_command("す す め") == "すすめ"
    assert canonical_command("こんにちは") is None


def test_canonical_commands_keeps_multiple_commands_in_order() -> None:
    assert canonical_commands("進め 止まれ") == ["すすめ", "とまれ"]
    assert canonical_commands("すすめとまれたたけ") == [
        "すすめ",
        "とまれ",
        "たたけ",
    ]
    assert canonical_commands("進め こんにちは") == []


def test_custom_words_are_converted_to_the_existing_commands() -> None:
    assignments = {
        "すすめ": "すいか",
        "とまれ": "うみ",
        "ひだり": "かに",
        "みぎ": "なつ",
        "たたけ": "われろ",
    }
    forms = custom_recognition_forms(assignments)

    assert canonical_commands("なつ すいか われろ", forms) == [
        "みぎ",
        "すすめ",
        "たたけ",
    ]
    assert canonical_commands("みぎ", forms) == []


@pytest.mark.parametrize(
    "assignments",
    [
        {
            "すすめ": "すいか",
            "とまれ": "すいか",
            "ひだり": "かに",
            "みぎ": "なつ",
            "たたけ": "われろ",
        },
        {
            "すすめ": "スイカ",
            "とまれ": "うみ",
            "ひだり": "かに",
            "みぎ": "なつ",
            "たたけ": "われろ",
        },
    ],
)
def test_custom_words_reject_duplicates_and_non_hiragana(
    assignments: dict[str, str],
) -> None:
    with pytest.raises(ValueError):
        custom_recognition_forms(assignments)
