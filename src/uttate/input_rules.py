from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ProtectedKind(StrEnum):
    KATAKANA_NAME = "katakana_name"
    PRESERVE_ENGLISH = "preserve_english"
    HIRAGANA = "hiragana"


@dataclass(frozen=True, slots=True)
class ProtectedTerm:
    kind: ProtectedKind
    source: str
    replacement: str


@dataclass(frozen=True, slots=True)
class ProtectedMask:
    placeholder: str
    kind: ProtectedKind
    source: str
    replacement: str


@dataclass(frozen=True, slots=True)
class ProtectedInput:
    text: str
    terms: tuple[ProtectedTerm, ...]


@dataclass(frozen=True, slots=True)
class MaskedProtectedInput:
    text: str
    masks: tuple[ProtectedMask, ...]

    def restore(self, text: str) -> str:
        restored = text
        for mask in self.masks:
            restored = restored.replace(mask.placeholder, mask.replacement)
        return restored


TAG_KINDS = {
    "\\": ProtectedKind.KATAKANA_NAME,
    "=": ProtectedKind.PRESERVE_ENGLISH,
    "$": ProtectedKind.HIRAGANA,
}


def parse_protected_input(raw_text: str) -> ProtectedInput:
    output: list[str] = []
    terms: list[ProtectedTerm] = []
    index = 0

    while index < len(raw_text):
        char = raw_text[index]
        if char not in TAG_KINDS:
            output.append(char)
            index += 1
            continue

        if _is_escaped_marker(raw_text, index, char):
            output.append(char)
            index += 2
            continue

        close_index = _find_closing_marker(raw_text, index + 1, char)
        if close_index is None:
            output.append(char)
            index += 1
            continue

        source = raw_text[index + 1 : close_index].strip()
        if not source:
            output.append(char)
            index += 1
            continue

        term = _protected_term(TAG_KINDS[char], source)
        terms.append(term)
        output.append(term.replacement)
        index = close_index + 1

    return ProtectedInput("".join(output), tuple(terms))


def mask_protected_input(raw_text: str) -> MaskedProtectedInput:
    output: list[str] = []
    masks: list[ProtectedMask] = []
    index = 0

    while index < len(raw_text):
        char = raw_text[index]
        if char not in TAG_KINDS:
            output.append(char)
            index += 1
            continue

        if _is_escaped_marker(raw_text, index, char):
            output.append(char)
            index += 2
            continue

        close_index = _find_closing_marker(raw_text, index + 1, char)
        if close_index is None:
            output.append(char)
            index += 1
            continue

        source = raw_text[index + 1 : close_index].strip()
        if not source:
            output.append(char)
            index += 1
            continue

        term = _protected_term(TAG_KINDS[char], source)
        placeholder = f"__UTTATE_PROTECTED_{len(masks)}__"
        masks.append(
            ProtectedMask(
                placeholder=placeholder,
                kind=term.kind,
                source=term.source,
                replacement=term.replacement,
            )
        )
        output.append(placeholder)
        index = close_index + 1

    return MaskedProtectedInput("".join(output), tuple(masks))


def protected_terms_prompt(terms: tuple[ProtectedTerm, ...]) -> str:
    if not terms:
        return "保護指定: (なし)"

    lines = ["保護指定:"]
    for term in terms:
        lines.append(f"- {term.kind.value}: `{term.source}` -> `{term.replacement}`")
    lines.extend(
        [
            "",
            "保護指定の制約:",
            "- 上記 replacement は出力候補内で必ずその表記のまま使う",
            "- preserve_english は翻訳・カタカナ化・大文字小文字変更をしない",
            "- katakana_name は指定済みのカタカナ表記を使う",
            "- hiragana は漢字化・カタカナ化せず、指定済みのひらがな表記を使う",
        ]
    )
    return "\n".join(lines)


def protected_masks_prompt(masks: tuple[ProtectedMask, ...]) -> str:
    if not masks:
        return "保護placeholder: (なし)"

    lines = ["保護placeholder:"]
    for mask in masks:
        lines.append(f"- {mask.kind.value}: `{mask.placeholder}`")
    lines.extend(
        [
            "",
            "保護placeholderの制約:",
            "- placeholder は出力候補内で必ずそのまま使う",
            "- placeholder の中身はアプリ側で復元するため、推測・翻訳・変換しない",
            "- placeholder を分割、削除、言い換え、大文字小文字変更しない",
        ]
    )
    return "\n".join(lines)


def _is_escaped_marker(text: str, index: int, marker: str) -> bool:
    return index + 1 < len(text) and text[index + 1] == marker


def _find_closing_marker(text: str, start: int, marker: str) -> int | None:
    index = start
    while index < len(text):
        if text[index] != marker:
            index += 1
            continue
        if _is_escaped_marker(text, index, marker):
            index += 2
            continue
        return index
    return None


def _protected_term(kind: ProtectedKind, source: str) -> ProtectedTerm:
    if kind == ProtectedKind.KATAKANA_NAME:
        replacement = romaji_to_katakana(source)
    elif kind == ProtectedKind.HIRAGANA:
        replacement = romaji_to_hiragana(source)
    else:
        replacement = source
    return ProtectedTerm(kind=kind, source=source, replacement=replacement)


def romaji_to_katakana(text: str) -> str:
    hiragana = romaji_to_hiragana(text)
    return "".join(chr(ord(char) + 0x60) if "ぁ" <= char <= "ゖ" else char for char in hiragana)


def romaji_to_hiragana(text: str) -> str:
    lowered = text.lower()
    result: list[str] = []
    index = 0

    while index < len(lowered):
        char = lowered[index]
        if not ("a" <= char <= "z"):
            result.append(text[index])
            index += 1
            continue

        if _is_double_consonant(lowered, index):
            result.append("っ")
            index += 1
            continue

        if char == "n":
            next_char = lowered[index + 1] if index + 1 < len(lowered) else ""
            if not next_char or next_char not in "aiueoyn":
                result.append("ん")
                index += 1
                continue
            if next_char == "n":
                result.append("ん")
                index += 1
                continue

        matched = False
        for size in (3, 2, 1):
            token = lowered[index : index + size]
            kana = ROMAJI_TABLE.get(token)
            if kana is None:
                continue
            result.append(kana)
            index += size
            matched = True
            break
        if not matched:
            result.append(text[index])
            index += 1

    return "".join(result)


def _is_double_consonant(text: str, index: int) -> bool:
    if index + 1 >= len(text):
        return False
    char = text[index]
    return char == text[index + 1] and char not in "aeioun"


ROMAJI_TABLE: dict[str, str] = {
    "a": "あ",
    "i": "い",
    "u": "う",
    "e": "え",
    "o": "お",
    "ka": "か",
    "ki": "き",
    "ku": "く",
    "ke": "け",
    "ko": "こ",
    "sa": "さ",
    "shi": "し",
    "si": "し",
    "su": "す",
    "se": "せ",
    "so": "そ",
    "ta": "た",
    "chi": "ち",
    "ti": "ち",
    "tsu": "つ",
    "tu": "つ",
    "te": "て",
    "to": "と",
    "na": "な",
    "ni": "に",
    "nu": "ぬ",
    "ne": "ね",
    "no": "の",
    "ha": "は",
    "hi": "ひ",
    "fu": "ふ",
    "hu": "ふ",
    "he": "へ",
    "ho": "ほ",
    "ma": "ま",
    "mi": "み",
    "mu": "む",
    "me": "め",
    "mo": "も",
    "ya": "や",
    "yu": "ゆ",
    "yo": "よ",
    "ra": "ら",
    "ri": "り",
    "ru": "る",
    "re": "れ",
    "ro": "ろ",
    "wa": "わ",
    "wo": "を",
    "ga": "が",
    "gi": "ぎ",
    "gu": "ぐ",
    "ge": "げ",
    "go": "ご",
    "za": "ざ",
    "ji": "じ",
    "zi": "じ",
    "zu": "ず",
    "ze": "ぜ",
    "zo": "ぞ",
    "da": "だ",
    "di": "ぢ",
    "du": "づ",
    "de": "で",
    "do": "ど",
    "ba": "ば",
    "bi": "び",
    "bu": "ぶ",
    "be": "べ",
    "bo": "ぼ",
    "pa": "ぱ",
    "pi": "ぴ",
    "pu": "ぷ",
    "pe": "ぺ",
    "po": "ぽ",
    "kya": "きゃ",
    "kyu": "きゅ",
    "kyo": "きょ",
    "sha": "しゃ",
    "shu": "しゅ",
    "sho": "しょ",
    "sya": "しゃ",
    "syu": "しゅ",
    "syo": "しょ",
    "cha": "ちゃ",
    "chu": "ちゅ",
    "cho": "ちょ",
    "tya": "ちゃ",
    "tyu": "ちゅ",
    "tyo": "ちょ",
    "nya": "にゃ",
    "nyu": "にゅ",
    "nyo": "にょ",
    "hya": "ひゃ",
    "hyu": "ひゅ",
    "hyo": "ひょ",
    "mya": "みゃ",
    "myu": "みゅ",
    "myo": "みょ",
    "rya": "りゃ",
    "ryu": "りゅ",
    "ryo": "りょ",
    "gya": "ぎゃ",
    "gyu": "ぎゅ",
    "gyo": "ぎょ",
    "ja": "じゃ",
    "ju": "じゅ",
    "jo": "じょ",
    "jya": "じゃ",
    "jyu": "じゅ",
    "jyo": "じょ",
    "bya": "びゃ",
    "byu": "びゅ",
    "byo": "びょ",
    "pya": "ぴゃ",
    "pyu": "ぴゅ",
    "pyo": "ぴょ",
    "fa": "ふぁ",
    "fi": "ふぃ",
    "fe": "ふぇ",
    "fo": "ふぉ",
    "va": "ゔぁ",
    "vi": "ゔぃ",
    "vu": "ゔ",
    "ve": "ゔぇ",
    "vo": "ゔぉ",
}
