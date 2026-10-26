"""Screen text adapted for the Korean-mode TTS voice.

Display text keeps its own spelling; only the copy on its way to the speech
server is converted.
"""

from __future__ import annotations

import re

from app.services.voice import pronounce

# LLM-authored pronunciation hints stay visible on screen, while TTS reads only
# their Hangul side so mixed-language terms do not inherit Korean-mode English.
_PRONUNCIATION = re.compile(
    r"(?<![A-Za-z])(?:[A-Za-z][A-Za-z0-9+.#/-]*(?: +[A-Za-z][A-Za-z0-9+.#/-]*)*)"
    r"\(([가-힣]+(?: +[가-힣]+)*)\)"
)


# Math notation cannot be spoken, so it is dropped rather than read out symbol by
# symbol. The prompt already asks for words instead; this is the net for when the
# model writes it anyway.
_MATH = re.compile(r"\$\$?.*?\$\$?|\\\[.*?\\\]|\\\(.*?\\\)|\\[A-Za-z]+\s*(?:\{[^}]*\})*")
_EMPTY_BRACKETS = re.compile(r"\s*[(（\[]\s*[)）\]]")
# Notation the model writes without any LaTeX around it, so _MATH cannot see it.
# Said rather than dropped: 'e^2' is part of the sentence, unlike a display formula.
# The Korean particle after it comes along, because the reading ends in a consonant
# where the notation did not -- 'e^2와' has to become '이의 2제곱과'.
_SUPERSCRIPT = re.compile(
    r"([A-Za-z0-9]+)\s*\^\s*(?:\{([^}]*)\}|(-?[A-Za-z0-9]+))(와|과|은|는|이|가|을|를)?"
)
_SUBSCRIPT = re.compile(r"([A-Za-z])\s*_\s*(?:\{([^}]*)\}|([A-Za-z0-9]+))")
# '제곱' ends in a consonant, so the particle that follows it is determined.
_AFTER_CONSONANT = {"와": "과", "과": "과", "는": "은", "은": "은",
                    "가": "이", "이": "이", "를": "을", "을": "을"}


def _say_superscript(match: re.Match[str]) -> str:
    base, exponent, particle = match.group(1), match.group(2) or match.group(3), match.group(4)
    return f"{base}의 {exponent}제곱{_AFTER_CONSONANT.get(particle or '', particle or '')}"


def _say_subscript(match: re.Match[str]) -> str:
    return f"{match.group(1)} {match.group(2) or match.group(3)}"
# A term written twice -- '소프트맥스 (softmax)' -- is said twice once the English
# is converted, which is what makes it sound odd aloud. Matched by what it reads
# as, not by being bracketed Latin: '(A)와 (B)' is two options, not a gloss.
_BRACKETED = re.compile(
    r"(?P<term>[가-힣]+)\s*[(（\[](?P<inner>[^)）\]]*[A-Za-z][^)）\]]*)[)）\]]"
)


def _drop_repeated_gloss(match: re.Match[str]) -> str:
    term = match.group("term")
    if pronounce.hangulize(match.group("inner").strip()) == term:
        return term
    return match.group(0)


def for_speech(text: str) -> str:
    """Adapt screen text for the TTS model without changing what is displayed.

    The voice runs in Korean mode, so Latin text reaches it mispronounced and can
    come out as a tonal artefact. Nothing Latin is allowed through: URLs are
    dropped, a pronunciation hint selects its Hangul side, and every remaining
    English term becomes the Hangul a Korean speaker would say. The original
    spelling stays intact on screen.
    """
    text = re.sub(
        r"\s*외부 출처\s*:?\s*(?:https?://\S+\s*,?\s*)+$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"https?://\S+", "", text)
    text = _PRONUNCIATION.sub(r"\1", text)
    text = _MATH.sub(" ", text)
    # Whatever the notation was bracketed in is now an empty pair to stumble over.
    text = _EMPTY_BRACKETS.sub("", text)
    text = _BRACKETED.sub(_drop_repeated_gloss, text)
    text = _SUPERSCRIPT.sub(_say_superscript, text)
    text = _SUBSCRIPT.sub(_say_subscript, text)
    return re.sub(r"\s{2,}", " ", pronounce.hangulize(text)).strip()
