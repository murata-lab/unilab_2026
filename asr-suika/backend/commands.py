"""Voskの認識結果をゲーム用の5命令へ正規化する。"""

from __future__ import annotations

import re
from collections.abc import Mapping

COMMANDS = [
    "すすめ",
    "とまれ",
    "ひだり",
    "みぎ",
    "たたけ",
]

# Voskが返しやすい漢字表記や送り仮名の揺れも受け入れる。
RECOGNITION_FORMS = {
    "すすめ": "すすめ",
    "進め": "すすめ",
    "進めー": "すすめ",
    "とまれ": "とまれ",
    "止まれ": "とまれ",
    "ひだり": "ひだり",
    "左": "ひだり",
    "みぎ": "みぎ",
    "右": "みぎ",
    "たたけ": "たたけ",
    "叩け": "たたけ",
}

HIRAGANA_WORD = re.compile(r"^[ぁ-ゖー]+$")


def custom_recognition_forms(assignments: Mapping[str, str]) -> dict[str, str]:
    """操作から登録語への対応を、Vosk用の認識候補へ変換する。"""
    if set(assignments) != set(COMMANDS):
        raise ValueError("5つすべての操作に言葉を登録してください")

    words = list(assignments.values())
    if any(
        not isinstance(word, str) or HIRAGANA_WORD.fullmatch(word) is None
        for word in words
    ):
        raise ValueError("登録語は空白なしのひらがなにしてください")
    if len(set(words)) != len(words):
        raise ValueError("同じ言葉を複数の操作には登録できません")

    return {word: command for command, word in assignments.items()}


def canonical_command(text: str) -> str | None:
    """空白を除去し、ゲームが扱うひらがなの命令へ変換する。"""
    compact_text = "".join(text.split())
    return RECOGNITION_FORMS.get(compact_text)


def canonical_commands(
    text: str,
    recognition_forms: Mapping[str, str] = RECOGNITION_FORMS,
) -> list[str]:
    """1回の認識結果に含まれる命令を、話した順番のまま返す。"""
    tokens = text.split()
    token_commands = [
        recognition_forms.get("".join(token.split())) for token in tokens
    ]
    if tokens and all(command is not None for command in token_commands):
        return [command for command in token_commands if command is not None]

    compact_text = "".join(tokens)
    if not compact_text:
        return []

    forms = sorted(
        recognition_forms.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    commands: list[str] = []
    offset = 0
    while offset < len(compact_text):
        matched = next(
            (
                (form, command)
                for form, command in forms
                if compact_text.startswith(form, offset)
            ),
            None,
        )
        if matched is None:
            return []
        form, command = matched
        commands.append(command)
        offset += len(form)
    return commands
