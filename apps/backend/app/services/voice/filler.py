"""Progress notices shown, and on the realtime path spoken, while the model works.

A reply is validated before any of it is released, so a slow turn is silence the
student cannot interpret. The notice covers that gap. A fixed "please wait" does
that once; on the tenth turn it is a recording, and the student stops hearing it
as speech. So the notice is composed per turn from the question itself:

* the question's **topic** is echoed back whenever it can be read off the
  sentence ("경사하강법이 뭐야?" → "경사하강법이요? 네, 잠깐 정리해 볼게요."). That is
  both the conversational cue a human tutor gives and the earliest signal that
  the agent heard the right words, so a misheard turn can be interrupted early;
* the **kind** of question chooses the phrasing: a definition, a why, a how, a
  comparison of two things, a request for an example, a yes/no check, or a
  question about where something is in the materials;
* two turns in a row never get the same notice;
* a turn that is not waiting for an answer — a greeting, thanks, "네, 알겠어요",
  a laugh — gets **no notice at all**. Nobody says "잠시만요" back to "안녕";
* a turn in which the student is **stuck** — "몰라", "모르겠어요", "어려워요", "힌트
  주세요" — is an answer to the tutor's question, not a question of its own. It
  gets a notice that promises a different angle and echoes nothing: "몰라" is a
  verb, and "몰라에 대해 설명해 드릴게요" was the notice that made this rule;
* a short reply to a tutor question that ended in "?" ("점수요", "비교하는 값") is
  the student's answer, so it is acknowledged, not echoed back as a new topic.

Picking is a pure function of the question, the session state and an injectable
random source, so it costs nothing on the turn and is testable. Both question
surfaces go through :func:`pick_filler`, so the typed and the spoken notice
cannot drift. The echoed words are the student's own; nothing here is model
output, which is why it may be spoken before any validation has run.
"""

from __future__ import annotations

import random
import re
from typing import Optional, Sequence

from app.services.voice import pronounce

# ---------------------------------------------------------------------------
# Phrasing
#
# Every notice is short: on the realtime path it is synthesized and played before
# the answer, so each extra syllable is dead air the answer waits behind.
# Placeholders: {topic}, {a}/{b} for a comparison, and the particles {yo} 이요/요,
# {i} 이/가, {eun} 은/는, {wa} 와/과, which follow the topic's final sound.
# ---------------------------------------------------------------------------

DEFINITION: tuple[str, ...] = (
    "{topic}{yo}? 네, 잠깐 정리해 볼게요.",
    "{topic}에 대해 정리해 볼게요. 잠시만요.",
    "{topic}, 좋은 질문이에요. 잠시만 기다려 주세요.",
    "{topic}{i} 뭔지부터 짚어 볼게요. 잠시만요.",
)
WHY: tuple[str, ...] = (
    "{topic}{yo}? 왜 그런지 잠깐 생각해 볼게요.",
    "{topic}, 이유를 정리해 볼게요. 잠시만요.",
    "{topic}{eun} 왜 그럴까요. 잠깐 짚어 볼게요.",
)
HOW: tuple[str, ...] = (
    "{topic}{eun} 어떻게 되는지 순서대로 볼게요.",
    "{topic} 과정을 잠깐 떠올려 볼게요. 잠시만요.",
    "{topic}, 어떻게 하는지 볼게요. 잠시만 기다려 주세요.",
)
DIFFERENCE: tuple[str, ...] = (
    "{a}{wa} {b}의 차이요? 네, 잠깐 정리해 볼게요.",
    "{a}{wa} {b}{eun} 어떻게 다른지 비교해 볼게요.",
    "{a}{wa} {b}, 헷갈리기 쉬운 부분이에요. 잠시만요.",
)
DIFFERENCE_ONE: tuple[str, ...] = (
    "{topic}의 차이를 정리해 볼게요. 잠시만요.",
    "{topic}{i} 어떻게 다른지 비교해 볼게요.",
)
EXAMPLE: tuple[str, ...] = (
    "{topic} 예시요? 네, 하나 떠올려 볼게요.",
    "{topic}{eun} 어떤 예가 잘 맞을지 잠깐 생각해 볼게요.",
    "{topic}에 맞는 예를 찾아볼게요. 잠시만요.",
)
WHETHER: tuple[str, ...] = (
    "{topic}{i} 맞는지 확인해 볼게요. 잠시만요.",
    "{topic}, 맞는지 한번 볼게요. 잠시만요.",
    "{topic}{yo}? 네, 한번 따져 볼게요.",
)
SEARCH_TOPIC: tuple[str, ...] = (
    "{topic}{i} 자료 어디에 나오는지 찾아볼게요.",
    "{topic}, 강의 자료에서 확인해 볼게요. 잠시만요.",
    "{topic} 관련 자료를 찾고 있어요. 잠시만요.",
)
DIFFICULTY: tuple[str, ...] = (
    "{topic}{yo}? 네, 쉬운 데서부터 차근차근 볼게요.",
    "{topic}{i} 어렵게 느껴지시군요. 잠깐 정리해 볼게요.",
    "{topic}, 어디서 막히는지 같이 볼게요. 잠시만요.",
)
EXPLAIN: tuple[str, ...] = (
    "{topic}에 대해 설명해 드릴게요. 잠깐 정리할게요.",
    "{topic}{yo}? 네, 잠시만요.",
    "{topic} 이야기네요. 어디서부터 볼지 잠깐 생각해 볼게요.",
)

# Without a readable topic the notice still follows the kind of question.
SEARCH: tuple[str, ...] = (
    "네, 강의 자료에서 찾아볼게요. 잠시만요.",
    "자료를 한번 확인해 볼게요. 잠시만 기다려 주세요.",
    "어디에 나오는지 자료를 살펴볼게요.",
)
WHY_PLAIN: tuple[str, ...] = (
    "왜 그런지 잠깐 생각해 볼게요.",
    "이유를 정리해서 말씀드릴게요. 잠시만요.",
)
HOW_PLAIN: tuple[str, ...] = (
    "어떻게 하는지 순서대로 정리해 볼게요.",
    "과정을 잠깐 떠올려 볼게요. 잠시만요.",
)
DIFFERENCE_PLAIN: tuple[str, ...] = (
    "어떤 점이 다른지 비교해 볼게요. 잠시만요.",
    "둘의 차이를 정리해 볼게요.",
)
EXAMPLE_PLAIN: tuple[str, ...] = (
    "좋은 예를 하나 떠올려 볼게요. 잠시만요.",
    "예시를 찾아볼게요. 잠시만 기다려 주세요.",
)
STUCK: tuple[str, ...] = (
    "음, 그럼 다른 쪽에서 접근해 볼게요. 잠시만요.",
    "네, 괜찮아요. 조금 더 쉬운 단계부터 볼게요.",
    "그럼 힌트를 하나 더 드릴게요. 잠시만요.",
    "네, 어디서 막혔는지 같이 볼게요. 잠시만요.",
)
ANSWER: tuple[str, ...] = (
    "네, 그렇게 보셨군요. 잠시만요.",
    "네, 그 답을 놓고 이어서 볼게요.",
    "음, 잠깐 살펴볼게요.",
    "네, 확인해 볼게요. 잠시만요.",
)
FOLLOW_UP: tuple[str, ...] = (
    "네, 이어서 볼게요. 잠시만요.",
    "그 부분이요? 잠깐 정리해 볼게요.",
    "네, 조금 더 생각해 볼게요.",
    "네, 잠시만요.",
)
GENERAL: tuple[str, ...] = (
    "질문을 살펴보고 있어요. 잠시만 기다려 주세요.",
    "네, 잠시만요. 생각해 볼게요.",
    "좋은 질문이에요. 잠깐 정리해 볼게요.",
    "네, 확인해 볼게요. 잠시만 기다려 주세요.",
    "음, 어떻게 설명하면 좋을지 잠깐 생각해 볼게요.",
    "잠시만요. 핵심부터 짚어 볼게요.",
)

_TOPIC_TEMPLATES = (
    DEFINITION
    + WHY
    + HOW
    + DIFFERENCE
    + DIFFERENCE_ONE
    + EXAMPLE
    + WHETHER
    + SEARCH_TOPIC
    + DIFFICULTY
    + EXPLAIN
)
_PLAIN_POOLS = (
    SEARCH,
    WHY_PLAIN,
    HOW_PLAIN,
    DIFFERENCE_PLAIN,
    EXAMPLE_PLAIN,
    STUCK,
    ANSWER,
    FOLLOW_UP,
    GENERAL,
)
# Every notice that carries no words of the student's own.
ALL_FILLERS: frozenset[str] = frozenset(text for pool in _PLAIN_POOLS for text in pool)

# ---------------------------------------------------------------------------
# Reading the question
# ---------------------------------------------------------------------------

_OPENERS = re.compile(
    r"^(?:그럼|그러면|근데|그런데|음+|아+|어+|네|예|저기|혹시|교수님|선생님|질문이요|질문\s*있어요|"
    r"궁금한\s*게\s*있는데|궁금한\s*게|하나\s*물어볼게요|물어볼게요|그니까|그러니까|저|제가)"
    r"[\s,.]+"
)
_TAIL_PUNCT = re.compile(r"[\s?!.,~…]+$")

# "자료 구조" is a subject, not a request to open the materials; a bare "페이지" is
# an OS topic, so only a numbered page counts.
_SEARCH_CUES = re.compile(
    r"자료(?!\s*구조)|강의\s*노트|교재|슬라이드|피디에프|pdf|(?:\d+|몇)\s*(?:페이지|쪽|장)\b|페이지에|"
    r"어디에?\s*(?:나오|나와|있|적혀)|찾아|출처",
    re.IGNORECASE,
)
# Everything in a materials question that is about the materials rather than
# the subject: removed before the subject is read.
_SEARCH_NOISE = re.compile(
    r"(?:강의|수업)?\s*자료(?:에서|에|를|는|은)?|강의\s*노트(?:에서|에)?|교재(?:에서|에)?|슬라이드(?:에서|에)?|"
    r"피디에프|pdf|(?:\d+|몇)\s*(?:페이지|쪽|장)(?:에|에서)?|페이지에|어디에?\s*(?:나오|나와|있|적혀)\S*|"
    r"(?:나오는|나온|있는|적힌|다룬|다루는)\s*(?:부분|곳|페이지|내용|장)?|부분|내용|"
    r"찾아\S*|출처\S*|알려\S*|보여\S*|말해\S*|줘|주세요",
    re.IGNORECASE,
)
_DIFFERENCE_CUES = re.compile(
    r"차이|다른\s*점|비교|구분|어떻게\s*달라|뭐가\s*달라|어떻게\s*다르|뭐가\s*다르|다른\s*(?:거|건|게)"
)
_EXAMPLE_CUES = re.compile(r"예시|예를|예가|사례|예로|보기를")
_WHY_CUES = re.compile(r"왜|이유|원인|때문")
_HOW_CUES = re.compile(
    r"어떻게|방법|과정|절차|어떤\s*식|어떤\s*순서|구하|계산|푸는|풀어|하는\s*법|하는\s*거"
)
_WHETHER_CUES = re.compile(
    r"맞아|맞나|맞는|맞죠|맞지|인가요|인가|인지|되나요|되는\s*거|될까|할\s*수\s*있|가능|아닌가|아니야|아냐"
)
_DIFFICULTY_CUES = re.compile(
    r"어려워|어렵|헷갈려|헷갈리|모르겠|몰라|이해가?\s*안|이해가?\s*잘\s*안|감이\s*안|힌트"
)
_DEFINITION_CUES = re.compile(r"뭐|무엇|뭔|무슨|어떤\s*거|어떤\s*건|개념|정의|이란|란\b|의미|뜻")
_EXPLAIN_CUES = re.compile(r"설명|알려|말해|가르쳐|얘기|이야기|소개|정리해")

_CUE_ORDER: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("search", _SEARCH_CUES),
    ("difference", _DIFFERENCE_CUES),
    ("example", _EXAMPLE_CUES),
    ("why", _WHY_CUES),
    ("how", _HOW_CUES),
    ("definition", _DEFINITION_CUES),
    ("whether", _WHETHER_CUES),
    ("difficulty", _DIFFICULTY_CUES),
    ("explain", _EXPLAIN_CUES),
)

_TOPIC_FOLLOWS_CUE = frozenset({"왜", "어떻게"})

# Turns that are talk, not a question: every word must be one of these for the
# turn to count as social, so "네 알겠어요 그럼 캐시가 뭐예요" still gets a notice.
_SOCIAL_WORD = (
    r"안녕(?:하세요|하십니까|히\s*계세요|히\s*가세요)?|하이|헬로|반가워요?|반갑습니다|"
    r"고마워요?|고맙습니다|감사(?:해요|합니다|드려요|드립니다)?|땡큐|"
    r"네|넵|넹|예|응|어|오|와|우와|헐|아하|아|음|오케이|ok|okay|콜|"
    r"좋아요?|좋네요|좋습니다|굿|알겠(?:어요|습니다|어|다)|알았(?:어요|어|다)|알겠|"
    r"이해(?:했어요|됐어요|했습니다|됐습니다|갔어요|했어|됐어)|"
    r"그렇구나|그렇군요|그렇네요|그래요?|그렇죠|맞아요?|맞네요|진짜요?|정말요?|레알|"
    r"수고(?:하세요|했어요|많으셨어요|하셨어요)?|잘\s*가|안녕히|바이|또\s*올게요|다음에\s*봐요?|"
    r"미안(?:해요|합니다)?|죄송(?:해요|합니다)?|"
    r"ㅋ+|ㅎ+|하하+|헤헤|히히"
)
_SOCIAL = re.compile(
    r"^(?:(?:" + _SOCIAL_WORD + r")[\s,.!~?…]*)+$",
    re.IGNORECASE,
)

# The student cannot answer: a whole turn made of not-knowing, difficulty or a
# request for a hint, allowing openers and a few particles around it.
_STUCK_WORD = (
    r"몰라요?|몰라서요?|모르겠(?:어요|습니다|어|다|는데요?|네요)?|모르(?:겠|는데요?|겠는데요?)|"
    r"잘\s*모르\S*|하나도\s*모르\S*|전혀\s*모르\S*|"
    r"어려워요?|어렵(?:네요|습니다|다|고요)|어려운데요?|헷갈려요?|헷갈리(?:네요|는데요?)|"
    r"기억이?\s*안\s*나요?|생각이?\s*안\s*나요?|모르겟\S*|"
    r"힌트\s*(?:좀\s*)?(?:주세요|줘요|줘|달라|주실래요|있어요|있나요)?|힌트|"
    r"패스|넘어가요|넘어갈게요|포기|글쎄요?|잘\s*모르겠\S*|"
    # Non-answers after a tutor question: the policy already counts these as stuck.
    r"그러게요?|그런가요?|그런가|그렇겠네요?|모르지요?|모르죠|잘\s*모르지"
)
_STUCK = re.compile(
    r"^(?:(?:" + _STUCK_WORD + r"|" + _SOCIAL_WORD + r"|그냥|저는|나는|전|난|이건|그건|그게|이게|그것도|이것도|그거도|저것도|이거도|그것은|그것|이것|"
    r"뭔지|뭔\s*말인지|무슨\s*말인지|무슨\s*뜻인지|어떻게|왜|하는지|되는지|이게|저건|아직|잘|"
    r"솔직히|사실|진짜|정말|좀|조금|다|하나도|전혀|전부|완전|아예|딱히)[\s,.!~?…]*)+$",
    re.IGNORECASE,
)
_ENDS_WITH_QUESTION = re.compile(r'''[?？][\s"'”’)\]]*$''')
_ANSWER_MAX_CHARS = 16

_FOLLOW_UP_OPENERS = re.compile(
    r"^(그럼|그러면|그런데|근데|그거|그건|그게|아니|다시|왜|또|그리고)\b"
)
_FOLLOW_UP_MAX_CHARS = 20

# Particles and connectives that end a topic phrase but are not part of it.
_TOPIC_TAIL = re.compile(
    r"(?:\s*(?:에\s*대해서?|에\s*대한|에서는|에서|이라는\s*게|라는\s*게|이라는|라는|이라고|라고|"
    r"하는\s*(?:게|건|것)|하는|되는|하기|되기|한|할|중에서|중에|중|"
    r"는\s*게|은\s*게|이란|란|이|가|은|는|을|를|의|에|로|으로|도|만|좀|요|이요))+$"
)
_PAIR_SPLIT = re.compile(r"\s*(?:이랑|랑|과|와|하고|,|\s+vs\.?\s+|대비)\s*")
_PAIR_TAIL = re.compile(r"(?:\s*(?:의|이|가|은|는|을|를|중에|중|둘이|둘은))+$")

# A "topic" that is a pronoun, a time word, or the assessment the SAFE guard is
# about to refuse, is not worth echoing back.
_NOT_A_TOPIC = frozenset(
    "이거 그거 저거 이것 그것 저것 이건 그건 저건 이게 그게 저게 여기 거기 이런 그런 저런 "
    "아까 방금 지금 오늘 내일 어제 시험 과제 숙제 답 정답 답안 문제 퀴즈 중간 기말 "
    "너 네 니 당신 선생님 교수님 제가 내가 나 우리 저희 그것도 이것도 "
    "조금 좀 더 자세히 자세하게 천천히 쉽게 간단히 간단하게 짧게 길게 다시 한번 빨리 "
    "전부 전체 다 모두 처음부터 그냥 아직 솔직히 사실 진짜 정말 글쎄 패스 "
    # Bare verbs and adjectives a student answers with; none is a concept.
    "몰라 모르겠어 몰라요 알아 알아요 알겠어 어려워 어려워요 쉬워 헷갈려 헷갈려요 못해 안돼 돼 해 봐 줘 "
    "좋아 싫어 맞아 아니 아냐 그래 응".split()
)
# Endings that mean the remaining text is still a clause, not a noun phrase.
_VERBISH_END = re.compile(
    r"(?:해요|해|하나요|하죠|했어|했나요|돼요|돼|되나요|됐어|이에요|예요|이야|야|인데|"
    r"거예요|거야|건가요|다|까|죠|줘|주세요|래|네|냐|니|지|"
    # Finite verb and adjective endings: 몰라, 모르겠어, 어려워, 헷갈려, 알아요,
    # 못 해, 안 돼. A noun phrase never ends this way; a bare answer often does.
    # Finite verb endings a noun phrase never has: 모르겠어, 어려운데요, 알겠습니다,
    # 못 해요, 안 돼. Bare 어/라/러 are left alone — 세마포어, 카메라, 컴파일러.
    r"겠어요?|겠는데요?|는데요?|은데요?|"
    r"[가-힣]+네요|[가-힣]+군요|[가-힣]+습니다|[가-힣]+ㅂ니다|않아요?|못\s*해요?|안\s*돼요?|안\s*나요?)$"
)
_TOPIC_MAX_CHARS = 14
_TOPIC_MAX_SPACES = 2
_WORD = re.compile(r"[가-힣A-Za-z0-9]")


def _clean(question: str) -> str:
    text = _TAIL_PUNCT.sub("", question.strip())
    for _ in range(3):
        stripped = _OPENERS.sub("", text)
        if stripped == text:
            break
        text = stripped
    return text.strip()


def _as_topic(candidate: str) -> Optional[str]:
    topic = _TOPIC_TAIL.sub("", candidate.strip())
    topic = re.sub(r"\s{2,}", " ", topic).strip(" ,.?!~")
    if (
        not _WORD.search(topic)
        or len(topic) > _TOPIC_MAX_CHARS
        or topic.count(" ") > _TOPIC_MAX_SPACES
        or _VERBISH_END.search(topic)
        or any(word in _NOT_A_TOPIC for word in topic.split())
    ):
        return None
    return topic


def _topic_or_last_segment(candidate: str) -> Optional[str]:
    """A topic, falling back to the part after the last "X에서" when the whole is too long."""
    topic = _as_topic(candidate)
    if topic is None and "에서 " in candidate:
        topic = _as_topic(candidate.rsplit("에서 ", 1)[1])
    return topic


def _search_topic(text: str) -> Optional[str]:
    subject = re.sub(r"\s{2,}", " ", _SEARCH_NOISE.sub(" ", text)).strip()
    return _as_topic(subject) if subject else None


def is_social(question: str) -> bool:
    """Whether the turn is talk rather than a question: a greeting, thanks, a reaction."""
    text = _TAIL_PUNCT.sub("", question.strip())
    return bool(text) and _SOCIAL.match(text) is not None


def is_stuck(question: str) -> bool:
    """Whether the turn says the student cannot answer: "몰라", "모르겠어요", "힌트 주세요"."""
    text = _TAIL_PUNCT.sub("", question.strip())
    if not text or is_social(text):
        return False
    return _STUCK.match(text) is not None and re.search(
        r"몰라|모르|어려|헷갈|기억|생각이|힌트|패스|넘어가|포기|글쎄|그러게|그런가|그렇겠", text
    ) is not None


def _tutor_asked(previous_turn: Optional[str]) -> bool:
    return bool(previous_turn) and _ENDS_WITH_QUESTION.search(previous_turn.strip()) is not None


def _read(question: str) -> tuple[str, Optional[str]]:
    """The kind of question and, when it can be read off, its topic."""
    if is_social(question):
        return "social", None
    if is_stuck(question):
        return "stuck", None
    text = _clean(question)
    if not text:
        return "social", None
    for kind, pattern in _CUE_ORDER:
        cue = pattern.search(text)
        if not cue:
            continue
        if kind == "search":
            return kind, _search_topic(text)
        before = text[: cue.start()].strip()
        if before:
            return kind, _topic_or_last_segment(before)
        if cue.group() in _TOPIC_FOLLOWS_CUE:
            # "왜 데드락이 생겨?": the topic follows the cue; drop the predicate.
            words = text[cue.end() :].split()
            return kind, (_as_topic(" ".join(words[:-1])) if len(words) >= 2 else None)
        # A cue word that opens the sentence ("계산 그래프가 뭐야") is part of the
        # topic, not the question; let a later cue decide.
    return "general", _as_topic(text)


def extract_pair(question: str) -> Optional[tuple[str, str]]:
    """The two things a comparison question sets against each other, or ``None``."""
    text = _clean(question)
    cue = _DIFFERENCE_CUES.search(text)
    if not cue:
        return None
    head = _PAIR_TAIL.sub("", text[: cue.start()].strip())
    parts = [part for part in _PAIR_SPLIT.split(head) if part.strip()]
    if len(parts) != 2:
        return None
    a, b = (_as_topic(part) for part in parts)
    if a and b:
        return a, b
    return None


def extract_topic(question: str) -> Optional[str]:
    """The noun phrase the question is about, in the student's own words, or ``None``.

    Reads the words before the question cue ("X가 뭐야", "X 설명해 줘", "X는 어떻게
    구해"), after a leading "왜"/"어떻게" ("왜 X가 생겨"), or what is left of a
    materials question once the words about the materials are removed. A bare
    noun phrase ("가상 메모리") is its own topic. Conservative on purpose: echoing
    the wrong words is worse than a general notice.
    """
    return _read(question)[1]


def classify(
    question: str, *, history_length: int = 0, previous_turn: Optional[str] = None
) -> str:
    """Which kind of question this is, which chooses the phrasing of the notice.

    ``previous_turn`` is what the tutor said last. When it ended in a question and
    the student's turn is short and carries no question cue of its own, the turn
    is the student's **answer**, not a new topic to echo back.
    """
    kind, _ = _read(question)
    if kind != "general":
        return kind
    text = _clean(question)
    if _tutor_asked(previous_turn) and len(text) <= _ANSWER_MAX_CHARS:
        return "answer"
    if history_length and (len(text) <= _FOLLOW_UP_MAX_CHARS or _FOLLOW_UP_OPENERS.match(text)):
        return "follow_up"
    return "general"


# ---------------------------------------------------------------------------
# Composing the notice
# ---------------------------------------------------------------------------

_DIGIT_HAS_CODA = {
    "0": True,
    "1": True,
    "2": False,
    "3": True,
    "4": False,
    "5": False,
    "6": True,
    "7": True,
    "8": True,
    "9": False,
}


def _ends_in_consonant(topic: str) -> bool:
    """Whether the topic, as it will be *said*, ends in a final consonant.

    Particles follow the sound, and a Latin term is spoken in Hangul, so the
    decision is made on the pronounced form: "TCP" is said 티씨피 and takes 요.
    """
    spoken = pronounce.hangulize(topic).rstrip()
    if not spoken:
        return True
    last = spoken[-1]
    if last in _DIGIT_HAS_CODA:
        return _DIGIT_HAS_CODA[last]
    code = ord(last) - 0xAC00
    if 0 <= code < 11172:
        return code % 28 != 0
    return True


def _particles(topic: str) -> dict[str, str]:
    consonant = _ends_in_consonant(topic)
    return {
        "yo": "이요" if consonant else "요",
        "i": "이" if consonant else "가",
        "eun": "은" if consonant else "는",
        "wa": "과" if consonant else "와",
    }


def _render(template: str, topic: str) -> str:
    return template.format(topic=topic, **_particles(topic))


def _render_pair(template: str, a: str, b: str) -> str:
    # {wa} follows a; {eun} follows b, the word it is attached to.
    return template.format(a=a, b=b, wa=_particles(a)["wa"], eun=_particles(b)["eun"])


_TOPIC_POOLS: dict[str, Sequence[str]] = {
    "definition": DEFINITION,
    "why": WHY,
    "how": HOW,
    "difference": DIFFERENCE_ONE,
    "example": EXAMPLE,
    "whether": WHETHER,
    "search": SEARCH_TOPIC,
    "difficulty": DIFFICULTY,
    "explain": EXPLAIN,
    "general": EXPLAIN,
    "follow_up": EXPLAIN,
}
_PLAIN_POOLS_BY_KIND: dict[str, Sequence[str]] = {
    "stuck": STUCK,
    "answer": ANSWER,
    "search": SEARCH,
    "why": WHY_PLAIN,
    "how": HOW_PLAIN,
    "difference": DIFFERENCE_PLAIN,
    "example": EXAMPLE_PLAIN,
    "difficulty": STUCK,
    "follow_up": FOLLOW_UP,
}


def candidates(
    question: str, *, history_length: int = 0, previous_turn: Optional[str] = None
) -> list[str]:
    """Every notice that fits this question, before the no-repeat rule; none for talk."""
    kind = classify(question, history_length=history_length, previous_turn=previous_turn)
    if kind == "social":
        return []
    if kind in ("stuck", "answer"):
        # The student's own words here are a verb or an answer, never a topic.
        return list(_PLAIN_POOLS_BY_KIND[kind])
    if kind == "difference":
        pair = extract_pair(question)
        if pair:
            return [_render_pair(template, *pair) for template in DIFFERENCE]
    topic = extract_topic(question)
    if topic:
        return [_render(template, topic) for template in _TOPIC_POOLS[kind]]
    return list(_PLAIN_POOLS_BY_KIND.get(kind, GENERAL))


def pick_filler(
    question: str,
    *,
    history_length: int = 0,
    previous: Optional[str] = None,
    previous_turn: Optional[str] = None,
    rng: Optional[random.Random] = None,
) -> Optional[str]:
    """Choose the progress notice for one turn, or ``None`` when the turn needs none.

    A greeting or an acknowledgement is not waiting for an answer, so it gets no
    notice: the caller shows and speaks nothing before the reply.
    ``previous`` is the notice this session heard last, so two turns in a row
    never sound the same. ``previous_turn`` is the tutor's last utterance: a short
    reply to a question it asked is treated as an answer, not echoed as a topic.
    Pass a seeded ``rng`` to make the choice reproducible.
    """
    pool = candidates(question, history_length=history_length, previous_turn=previous_turn)
    if not pool:
        return None
    options = [text for text in pool if text != previous] or pool
    return (rng or random).choice(options)


def _template_regex(template: str) -> re.Pattern[str]:
    pattern = re.escape(template)
    for key, alternatives in (
        ("topic", "(.+?)"),
        ("a", "(.+?)"),
        ("b", "(.+?)"),
        ("yo", "(?:이요|요)"),
        ("i", "(?:이|가)"),
        ("eun", "(?:은|는)"),
        ("wa", "(?:와|과)"),
    ):
        pattern = pattern.replace(re.escape("{" + key + "}"), alternatives)
    return re.compile("^" + pattern + "$")


_TEMPLATE_REGEXES = tuple(_template_regex(template) for template in _TOPIC_TEMPLATES)


def is_progress_notice(text: str) -> bool:
    """Whether ``text`` is something :func:`pick_filler` could have produced."""
    return text in ALL_FILLERS or any(regex.match(text) for regex in _TEMPLATE_REGEXES)
