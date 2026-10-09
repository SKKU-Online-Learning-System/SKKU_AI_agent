"""English reaching the Korean voice, and what it is said as."""

from __future__ import annotations

import re

import pytest

from app.services.voice import pronounce


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # The table carries the course vocabulary, which no rule engine derives.
        ("softmax", "소프트맥스"),
        ("attention", "어텐션"),
        ("queue", "큐"),
        ("cache", "캐시"),
        # Acronyms are read letter by letter, the Korean convention already.
        ("HTTP", "에이치티티피"),
        ("GPU", "지피유"),
        # Except the ones said as a word.
        ("RAM", "램"),
        ("JSON", "제이슨"),
        # A plural keeps its stem's reading.
        ("vectors", "벡터스"),
        ("CPUs", "씨피유스"),
        # An identifier is said part by part.
        ("MyCPU", "마이씨피유"),
        # A lone letter is its name: 'Q와 K의 유사도'.
        ("Q", "큐"),
    ],
)
def test_known_terms_are_said_the_way_the_field_says_them(written, spoken) -> None:
    assert pronounce.say(written) == spoken


@pytest.mark.parametrize(
    ("written", "spoken"),
    [
        # A silent 'e' is not said but lengthens the vowel before it...
        ("make", "메이크"),
        ("line", "라인"),
        # ...unless a doubled consonant marks that vowel short.
        ("apple", "애플"),
        ("table", "테이블"),
        # An 'r' with no vowel after it colours the vowel instead of being said.
        ("server", "서버"),
        ("order", "오더"),
        # A stop may end a syllable straight after a short vowel, not otherwise.
        ("back", "백"),
        ("desk", "데스크"),
        # An obstruent before l is one cluster, and the l is also the next onset.
        ("flush", "플러시"),
        ("block", "블록"),
        # Endings whose spelling says nothing about the reading.
        ("action", "액션"),
        ("question", "퀘스천"),
        ("bridge", "브리지"),
        ("vision", "비전"),
    ],
)
def test_unknown_words_fall_back_to_a_sayable_approximation(written, spoken) -> None:
    """English spelling does not determine pronunciation, so this is an
    approximation. Its job is to leave the voice something Korean to say."""
    assert pronounce.transliterate(written) == spoken


def test_nothing_latin_survives() -> None:
    """The one hard guarantee: whatever the model writes, the voice gets Hangul.

    Anything Latin reaching the Korean voice is mispronounced and can come out as
    a tonal artefact, so an unknown word must still be converted, not passed on.
    """
    sentences = [
        "gradient descent에서 learning rate가 크면 diverge합니다.",
        "TCP/IP와 REST API를 zzyzx 방식으로 씁니다.",
        "back-end에서 getUserName을 호출하세요.",
    ]
    for sentence in sentences:
        spoken = pronounce.hangulize(sentence)
        assert not re.search(r"[A-Za-z]", spoken), spoken


def test_korean_and_numbers_are_left_alone() -> None:
    assert pronounce.hangulize("가상 메모리는 3페이지에 있습니다.") == "가상 메모리는 3페이지에 있습니다."


def test_every_syllable_produced_is_a_real_hangul_syllable() -> None:
    """A composition slip would emit a jamo cluster the voice cannot read."""
    for word in ["xylophone", "strength", "queue", "rhythm", "psychology", "jjaltteuk"]:
        for character in pronounce.transliterate(word):
            assert "가" <= character <= "힣", (word, character)
