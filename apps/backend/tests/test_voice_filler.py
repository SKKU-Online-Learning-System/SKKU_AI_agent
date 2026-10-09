"""The progress notice is composed from the question and varies per turn."""

import random

import pytest

from app.services.voice.filler import (
    ALL_FILLERS,
    ANSWER,
    FOLLOW_UP,
    GENERAL,
    SEARCH,
    STUCK,
    candidates,
    classify,
    extract_pair,
    extract_topic,
    is_progress_notice,
    is_social,
    is_stuck,
    pick_filler,
)


def test_consecutive_turns_never_repeat_the_notice() -> None:
    rng = random.Random(7)
    previous = None
    for _ in range(50):
        notice = pick_filler("가상 메모리 설명해 줘", previous=previous, rng=rng)
        assert notice != previous
        previous = notice


def test_the_notice_varies_across_turns_and_is_always_recognisable() -> None:
    rng = random.Random(3)
    seen = {pick_filler("페이지 교체 알고리즘 비교해 줘", rng=rng) for _ in range(30)}
    assert len(seen) > 1
    assert all(is_progress_notice(text) for text in seen)


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("경사하강법이 뭐야?", "경사하강법"),
        ("그럼 가상 메모리가 무엇인가요", "가상 메모리"),
        ("세마포어란 뭔가요", "세마포어"),
        ("TCP에 대해 설명해 주세요", "TCP"),
        ("가상 메모리 설명해 줘", "가상 메모리"),
        ("역전파는 어떻게 계산해?", "역전파"),
        ("왜 데드락이 생겨?", "데드락"),
        ("정규화를 하는 이유가 뭐예요", "정규화"),
        ("오버피팅 예시 좀 들어줘", "오버피팅"),
        ("소프트맥스가 확률 분포 맞아요?", "소프트맥스가 확률 분포"),
        ("강의 자료에서 세마포어 어디에 나와?", "세마포어"),
        ("슬라이드에 데드락 나오는 부분 찾아 줘", "데드락"),
        ("계산 그래프가 뭐야", "계산 그래프"),
        ("자료 구조에서 스택이 뭐야", "자료 구조에서 스택"),
        ("네 그럼 캐시가 뭐예요", "캐시"),
        ("CPU 스케줄링에서 라운드 로빈이 어떻게 동작하는지 알려주세요", "라운드 로빈"),
        ("L2 정규화", "L2 정규화"),
    ],
)
def test_the_topic_is_read_off_the_question_in_the_students_words(question, topic) -> None:
    assert extract_topic(question) == topic


@pytest.mark.parametrize(
    "question",
    [
        "이게 뭐예요?",
        "그거 뭐야",
        "왜 그런 거예요?",
        "시험 답 알려 줘",
        "조금 더 자세히",
        "다시 설명해 주세요",
        "음 그러니까 제가 지금 헷갈리는 게 뭐냐면",
    ],
)
def test_no_topic_is_echoed_when_the_question_does_not_name_one(question) -> None:
    assert extract_topic(question) is None
    rng = random.Random(0)
    for _ in range(10):
        assert pick_filler(question, history_length=2, rng=rng) in ALL_FILLERS


def test_the_kind_of_question_shapes_the_notice() -> None:
    assert classify("경사하강법이 뭐야?") == "definition"
    assert classify("왜 데드락이 생겨?") == "why"
    assert classify("역전파는 어떻게 계산해?") == "how"
    assert classify("프로세스랑 스레드의 차이가 뭐야?") == "difference"
    assert classify("오버피팅 예시 좀 들어줘") == "example"
    assert classify("소프트맥스가 확률 분포 맞아요?") == "whether"
    assert classify("강의 자료 몇 페이지에 나와?") == "search"
    # "자료 구조" is a subject and a bare "페이지" an OS topic, not the materials.
    assert classify("자료 구조에서 스택이 뭐야") == "definition"
    assert classify("페이지 교체 알고리즘 비교해 줘") == "difference"


def test_notices_are_phrased_for_the_kind_of_question() -> None:
    assert all("왜" in text or "이유" in text for text in candidates("왜 데드락이 생겨?"))
    assert all("어떻게" in text or "과정" in text for text in candidates("역전파는 어떻게 계산해?"))
    assert all("예" in text for text in candidates("오버피팅 예시 좀 들어줘"))
    assert all("자료" in text for text in candidates("강의 자료에서 세마포어 어디에 나와?"))
    assert all("데드락" in text for text in candidates("왜 데드락이 생겨?"))


def test_a_comparison_names_both_things() -> None:
    assert extract_pair("프로세스랑 스레드의 차이가 뭐야?") == ("프로세스", "스레드")
    assert extract_pair("TCP와 UDP는 어떻게 달라요") == ("TCP", "UDP")
    assert extract_pair("뮤텍스 세마포어 차이") is None, "no connective, so no guessed split"
    for text in candidates("프로세스랑 스레드의 차이가 뭐야?"):
        assert "프로세스와 스레드" in text


def test_particles_follow_the_sound_of_the_topic_as_spoken() -> None:
    assert "경사하강법이요?" in " ".join(candidates("경사하강법이 뭐야?"))
    assert "세마포어요?" in " ".join(candidates("세마포어가 뭐야?"))
    # "TCP" is spoken 티씨피, which ends in a vowel.
    assert "TCP요?" in " ".join(candidates("TCP가 뭐야?"))
    assert "프로세스와 스레드" in " ".join(candidates("프로세스랑 스레드 차이"))
    assert "뮤텍스과" not in " ".join(candidates("뮤텍스랑 세마포어 차이"))
    assert "뮤텍스와 세마포어는" in " ".join(candidates("뮤텍스랑 세마포어 차이"))


def test_a_short_turn_into_a_conversation_without_a_topic_is_a_follow_up() -> None:
    assert classify("그럼 그건요?", history_length=2) == "follow_up"
    assert classify("조금 더 자세히", history_length=4) == "follow_up"
    assert classify("조금 더 자세히", history_length=0) == "general"
    rng = random.Random(1)
    assert pick_filler("그럼 그건요?", history_length=2, rng=rng) in FOLLOW_UP
    # A bare term in an ongoing conversation is still echoed, not waved through.
    assert "가상 메모리" in pick_filler("가상 메모리", history_length=2, rng=rng)


def test_materials_questions_without_a_subject_still_mention_the_materials() -> None:
    rng = random.Random(1)
    assert pick_filler("교재 3페이지 내용 설명해 줘", rng=rng) in SEARCH


@pytest.mark.parametrize(
    "utterance",
    [
        "안녕",
        "안녕하세요!",
        "고마워",
        "감사합니다.",
        "네",
        "네, 알겠어요",
        "아 그렇구나 감사해요",
        "오케이",
        "ㅋㅋㅋ",
        "진짜요?",
        "수고하세요~",
        "   ",
    ],
)
def test_talk_that_is_not_waiting_for_an_answer_gets_no_notice(utterance) -> None:
    """Nobody says "잠시만요" back to "안녕"."""
    assert is_social(utterance) or not utterance.strip()
    assert classify(utterance, history_length=2) == "social"
    assert candidates(utterance) == []
    assert pick_filler(utterance, history_length=2, rng=random.Random(0)) is None


@pytest.mark.parametrize(
    "question",
    [
        "네 알겠어요 그럼 캐시가 뭐예요",
        "안녕하세요 경사하강법이 뭐예요",
        "감사합니다 그런데 왜 그런 거예요",
        "가상 메모리",
        "왜요?",
    ],
)
def test_a_question_wrapped_in_pleasantries_still_gets_a_notice(question) -> None:
    assert not is_social(question)
    assert pick_filler(question, history_length=2, rng=random.Random(0)) is not None


@pytest.mark.parametrize(
    "utterance",
    [
        "몰라",
        "몰라.",
        "모르겠어",
        "음 몰라요",
        "잘 모르겠어요",
        "그냥 몰라",
        "어려워요",
        "힌트 좀 주세요",
        "패스",
        "기억이 안 나요",
        "그러게.",
        "그것도 잘 모르겠어",
        "음, 그런가요",
    ],
)
def test_a_stuck_student_is_promised_another_angle_and_echoed_nothing(utterance) -> None:
    """"몰라" is a verb: "몰라에 대해 설명해 드릴게요" was the notice that made this rule."""
    assert is_stuck(utterance)
    assert classify(utterance, history_length=2) == "stuck"
    assert extract_topic(utterance) is None
    for _ in range(10):
        notice = pick_filler(utterance, history_length=2, rng=random.Random(0))
        assert notice in STUCK
        assert "몰라" not in notice and "모르" not in notice


@pytest.mark.parametrize(
    ("question", "topic"),
    [
        ("소프트맥스 연산이 뭔지 모르겠어", "소프트맥스 연산"),
        ("역전파가 어려워요", "역전파"),
        ("경사하강법 힌트 주세요", "경사하강법"),
    ],
)
def test_not_knowing_a_named_concept_is_a_question_about_it(question, topic) -> None:
    assert not is_stuck(question)
    assert extract_topic(question) == topic


@pytest.mark.parametrize(
    "utterance",
    ["그냥 설명해줘", "알아요", "안 돼", "어려워", "모르겠어"],
)
def test_a_verb_or_an_adverb_is_never_echoed_as_a_topic(utterance) -> None:
    assert extract_topic(utterance) is None
    notice = pick_filler(utterance, history_length=2, rng=random.Random(0))
    assert notice is None or notice in ALL_FILLERS


def test_a_short_reply_to_the_tutors_question_is_an_answer_not_a_topic() -> None:
    asked = "점수라는 말에서 점수가 무엇을 의미할까요?"
    for reply in ("점수요", "비교하는 값", "유사도 아닐까요", "내적 값이요"):
        assert classify(reply, history_length=2, previous_turn=asked) == "answer"
        notice = pick_filler(reply, history_length=2, previous_turn=asked, rng=random.Random(0))
        assert notice in ANSWER
        assert reply.rstrip("요") not in notice
    # A real question after a tutor question is still read as one.
    assert classify("그럼 소프트맥스는 뭐예요?", history_length=2, previous_turn=asked) == "definition"
    # Without a question from the tutor a bare term is echoed as before.
    told = "점수는 두 벡터의 내적이에요."
    assert classify("가상 메모리", history_length=2, previous_turn=told) == "follow_up"
    assert "가상 메모리" in pick_filler("가상 메모리", history_length=2, previous_turn=told)


def test_every_fixed_notice_is_short_enough_to_speak_before_the_answer() -> None:
    assert all(len(text) <= 32 for text in ALL_FILLERS)
    assert GENERAL[0] == "질문을 살펴보고 있어요. 잠시만 기다려 주세요."
