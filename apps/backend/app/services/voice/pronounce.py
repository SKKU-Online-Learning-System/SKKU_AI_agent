"""Read Latin-script terms aloud in Korean.

The TTS voice runs in Korean mode. Latin text handed to it is mispronounced and
can come out as a tonal artefact, so nothing Latin may reach synthesis: every
English word is converted to the Hangul a Korean speaker would actually say.

Three layers, best first:

1. ``TERMS`` — the vocabulary these courses actually use, spelled the way the
   field spells it. A table beats any rule engine and is the only way to get
   'queue' or 'cache' right.
2. Acronyms — read letter by letter, which is already the Korean convention.
3. :func:`transliterate` — a grapheme walk for everything else. English spelling
   is irregular, so this is an approximation; it exists so an unknown word is
   still *sayable* rather than handed to the voice as Latin.

Display text is never touched; this runs only on its way to the speech server.
"""

from __future__ import annotations

import re

_ONSETS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_VOWELS = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_CODAS = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"

# Letter names, for acronyms read one letter at a time.
LETTERS = {
    "a": "에이", "b": "비", "c": "씨", "d": "디", "e": "이", "f": "에프",
    "g": "지", "h": "에이치", "i": "아이", "j": "제이", "k": "케이", "l": "엘",
    "m": "엠", "n": "엔", "o": "오", "p": "피", "q": "큐", "r": "알",
    "s": "에스", "t": "티", "u": "유", "v": "브이", "w": "더블유", "x": "엑스",
    "y": "와이", "z": "제트",
}

# Acronyms conventionally said as a word instead of spelled out.
ACRONYM_WORDS = {
    "ram": "램", "rom": "롬", "json": "제이슨", "rest": "레스트", "sql": "에스큐엘",
    "gui": "지유아이", "ascii": "아스키", "cpu": "씨피유", "gpu": "지피유",
    "ai": "에이아이", "os": "오에스", "io": "아이오", "url": "유알엘",
}

# The vocabulary of these courses, plus the English a tutor drops into Korean.
# Spelled as the field says them, which no rule engine can derive.
TERMS = {
    # machine learning
    "softmax": "소프트맥스", "attention": "어텐션", "transformer": "트랜스포머",
    "gradient": "그래디언트", "descent": "디센트", "embedding": "임베딩",
    "token": "토큰", "vector": "벡터", "matrix": "매트릭스", "tensor": "텐서",
    "loss": "로스", "epoch": "에포크", "batch": "배치", "layer": "레이어",
    "model": "모델", "dropout": "드롭아웃", "encoder": "인코더", "decoder": "디코더",
    "query": "쿼리", "key": "키", "value": "밸류", "neural": "뉴럴",
    "network": "네트워크", "learning": "러닝", "machine": "머신", "deep": "딥",
    "training": "트레이닝", "dataset": "데이터셋", "feature": "피처",
    "label": "레이블", "bias": "바이어스", "weight": "웨이트", "sigmoid": "시그모이드",
    "relu": "렐루", "activation": "액티베이션", "normalization": "노멀라이제이션",
    "normalize": "노멀라이즈", "regression": "리그레션", "overfitting": "오버피팅",
    "backpropagation": "백프로퍼게이션", "exponential": "엑스포넨셜",
    "parameter": "파라미터", "inference": "인퍼런스", "prompt": "프롬프트",
    # operating systems
    "process": "프로세스", "thread": "스레드", "memory": "메모리",
    "virtual": "버추얼", "page": "페이지", "paging": "페이징", "cache": "캐시",
    "kernel": "커널", "scheduler": "스케줄러", "deadlock": "데드락",
    "semaphore": "세마포어", "mutex": "뮤텍스", "buffer": "버퍼", "stack": "스택",
    "heap": "힙", "register": "레지스터", "interrupt": "인터럽트",
    "segment": "세그먼트", "file": "파일", "system": "시스템", "disk": "디스크",
    "context": "컨텍스트", "switch": "스위치",
    # software engineering and general computing
    "server": "서버", "client": "클라이언트", "database": "데이터베이스",
    "function": "펑션", "class": "클래스", "object": "오브젝트", "method": "메서드",
    "variable": "베리어블", "array": "어레이", "loop": "루프", "string": "스트링",
    "integer": "인티저", "boolean": "불리언", "compiler": "컴파일러",
    "debug": "디버그", "test": "테스트", "code": "코드", "data": "데이터",
    "index": "인덱스", "queue": "큐", "list": "리스트", "node": "노드",
    "tree": "트리", "graph": "그래프", "hash": "해시", "sort": "소트",
    "search": "서치", "input": "인풋", "output": "아웃풋", "error": "에러",
    "update": "업데이트", "version": "버전", "library": "라이브러리",
    "framework": "프레임워크", "algorithm": "알고리즘", "pointer": "포인터",
    "byte": "바이트", "bit": "비트", "request": "리퀘스트", "response": "리스폰스",
    "backend": "백엔드", "frontend": "프론트엔드", "callback": "콜백",
    "runtime": "런타임", "timeout": "타임아웃", "endpoint": "엔드포인트",
    # everyday English a tutor mixes in
    "ok": "오케이", "okay": "오케이", "yes": "예스", "no": "노",
    "example": "이그잼플", "point": "포인트", "level": "레벨", "step": "스텝",
    "check": "체크", "start": "스타트", "end": "엔드", "size": "사이즈",
    "type": "타입", "case": "케이스", "group": "그룹", "set": "셋",
    "my": "마이", "user": "유저", "get": "겟", "name": "네임", "new": "뉴",
    "true": "트루", "false": "폴스", "null": "널", "void": "보이드",
}

# Vowel spellings, longest first. A value may span syllables ("ou" -> 아우).
_VOWEL_RULES: list[tuple[str, str]] = [
    ("eau", "ㅗ"), ("iou", "ㅣㅓ"), ("eou", "ㅣㅓ"),
    ("you", "ㅠ"), ("yea", "ㅣ"), ("yie", "ㅣ"), ("way", "ㅞㅣ"), ("wai", "ㅞㅣ"),
    # Upper case marks what the normalizer rewrote: a vowel lengthened by a
    # silent 'e' (A E I O U) and an r-coloured vowel (Q R Z), neither of which
    # the spelling shows.
    ("A", "ㅔㅣ"), ("I", "ㅏㅣ"), ("O", "ㅗ"), ("U", "ㅠ"), ("E", "ㅣ"),
    ("Q", "ㅏ"), ("R", "ㅓ"), ("Z", "ㅗ"), ("Y", "ㅕ"),
    ("ai", "ㅔㅣ"), ("ay", "ㅔㅣ"), ("ei", "ㅔㅣ"), ("ey", "ㅣ"),
    ("ee", "ㅣ"), ("ea", "ㅣ"), ("ie", "ㅣ"), ("eu", "ㅠ"),
    ("oo", "ㅜ"), ("ou", "ㅏㅜ"), ("ow", "ㅗㅜ"), ("oa", "ㅗ"),
    ("oi", "ㅗㅣ"), ("oy", "ㅗㅣ"), ("au", "ㅗ"), ("aw", "ㅗ"),
    ("ia", "ㅣㅏ"), ("io", "ㅣㅗ"), ("ue", "ㅜ"), ("ui", "ㅜㅣ"),
    # w and y glide onto the vowel after them rather than standing alone.
    ("wa", "ㅝ"), ("wo", "ㅝ"), ("we", "ㅞ"), ("wi", "ㅟ"), ("wu", "ㅜ"),
    ("ya", "ㅑ"), ("yo", "ㅛ"), ("ye", "ㅖ"), ("yu", "ㅠ"), ("yi", "ㅣ"),
    ("a", "ㅐ"), ("e", "ㅔ"), ("i", "ㅣ"), ("o", "ㅗ"), ("u", "ㅓ"),
    ("y", "ㅣ"), ("w", "ㅜ"),
]

# Consonant spellings, longest first.
_CONSONANT_RULES: list[tuple[str, str]] = [
    ("tch", "ㅊ"), ("ch", "ㅊ"), ("sh", "ㅅ"), ("th", "ㅅ"),
    ("ng", "ㅇ"), ("ck", "ㄱ"), ("ph", "ㅍ"), ("gh", "ㄱ"), ("wh", "ㅇ"),
    ("b", "ㅂ"), ("c", "ㅋ"), ("d", "ㄷ"), ("f", "ㅍ"), ("g", "ㄱ"),
    ("h", "ㅎ"), ("j", "ㅈ"), ("k", "ㅋ"), ("l", "ㄹ"), ("m", "ㅁ"),
    ("n", "ㄴ"), ("p", "ㅍ"), ("q", "ㅋ"), ("r", "ㄹ"), ("s", "ㅅ"),
    ("t", "ㅌ"), ("v", "ㅂ"), ("x", "ㅋ"), ("z", "ㅈ"),
]

# Consonants Korean can carry as a final, so they do not each grow a syllable.
# Sonorants always may. A stop only may straight after a plain short vowel --
# 'back' is 백 but 'make' is 메이크 and 'desk' is 데스크, never 메익 or 데슥.
_AS_CODA = {"ㄴ": "ㄴ", "ㅁ": "ㅁ", "ㅇ": "ㅇ", "ㄹ": "ㄹ"}
_AS_CODA_AFTER_SHORT = {"ㄱ": "ㄱ", "ㅋ": "ㄱ", "ㅂ": "ㅂ", "ㅍ": "ㅂ"}
# A bare consonant otherwise becomes its own syllable. Sibilants take ㅣ the way
# 'bridge' is 브리지, everything else takes ㅡ the way 'desk' is 데스크.
_BARE_VOWEL = {"ㅈ": "ㅣ", "ㅊ": "ㅣ"}


def _syllable(onset: str, vowel: str, coda: str = " ") -> str:
    return chr(
        0xAC00 + (_ONSETS.index(onset) * 21 + _VOWELS.index(vowel)) * 28 + _CODAS.index(coda)
    )


def _normalize(word: str) -> str:
    """Fold the spellings whose rules are simpler once rewritten."""
    word = word.lower()
    if word.startswith(("kn", "gn", "pn")):
        word = "n" + word[2:]
    if word.startswith("wr"):
        word = "r" + word[2:]
    word = word.replace("sch", "sk").replace("qu", "kw").replace("x", "ks")
    # Endings whose spelling says nothing about how they are read.
    word = re.sub(r"dge$", "j", word)
    # '-tion' is 션 after most stems but 천 after s: 액션, 펑션, but 퀘스천.
    word = re.sub(r"stion$", "schun", word)
    word = re.sub(r"tion$", "shYn", word)
    word = re.sub(r"sion$", "jun", word)
    # Unstressed '-om'/'-on' reduces: 랜덤, 커스텀, 퍼슨.
    if len(word) > 3:
        word = re.sub(r"om$", "Rm", word)
    word = re.sub(r"([^aeiou])ge$", r"\1j", word)
    word = re.sub(r"sh$", "shi", word)
    # An 'r' with no vowel after it colours the vowel before it instead of being
    # said: 'server' is 서버, not 세르베르.
    word = re.sub(r"ar(?![aeiouy])", "Q", word)
    word = re.sub(r"or(?![aeiouy])", "Z", word)
    word = re.sub(r"[eiu]r(?![aeiouy])", "R", word)
    if len(word) > 3 and word.endswith("e") and word[-2] not in "aeiouy":
        # Mark the vowel this silent 'e' lengthens, then drop the 'e' itself.
        body = word[:-1]
        match = re.search(r"([aeiou])([^aeiou]{1,2})$", body)
        if match:
            body = (
                body[: match.start(1)]
                + {"a": "A", "e": "E", "i": "I", "o": "O", "u": "U"}[match.group(1)]
                + match.group(2)
            )
        word = body
    return re.sub(r"([bcdfgklmnprstz])\1", r"\1", word)


def _match(rules: list[tuple[str, str]], word: str, index: int) -> tuple[str, str] | None:
    for spelling, jamo in rules:
        if word.startswith(spelling, index):
            return spelling, jamo
    return None


def transliterate(word: str) -> str:
    """Approximate one English word as Hangul.

    English orthography does not determine pronunciation, so this is deliberately
    an approximation: its job is to leave the speech server something Korean to
    say. Known words should be in :data:`TERMS` instead.
    """
    word = _normalize(word)
    syllables: list[str] = []
    # Whether each syllable came from a plain short vowel, which is what decides
    # if a following stop may become its final.
    short: list[bool] = []
    pending: str | None = None
    index = 0

    def add(onset: str, vowel: str, is_short: bool) -> None:
        syllables.append(_syllable(onset, vowel))
        short.append(is_short)

    def flush_pending() -> None:
        """Place a consonant that never found a vowel of its own."""
        nonlocal pending
        if pending is None:
            return
        coda = _AS_CODA.get(pending)
        if coda is None and syllables and short[-1]:
            coda = _AS_CODA_AFTER_SHORT.get(pending)
        if coda and syllables and _has_no_coda(syllables[-1]):
            syllables[-1] = _with_coda(syllables[-1], coda)
        else:
            add(pending, _BARE_VOWEL.get(pending, "ㅡ"), False)
        pending = None

    while index < len(word):
        vowel = _match(_VOWEL_RULES, word, index)
        if vowel is not None:
            spelling, jamo = vowel
            is_short = len(jamo) == 1 and len(spelling) == 1 and spelling.islower()
            for offset, single in enumerate(jamo):
                add(pending if offset == 0 and pending else "ㅇ", single, is_short)
            pending = None
            index += len(spelling)
            continue
        consonant = _match(_CONSONANT_RULES, word, index)
        if consonant is not None:
            spelling, jamo = consonant
            # An obstruent followed by l is one cluster: 'flush' is 플러시, and the
            # l is both the final of that syllable and the onset of the next.
            if spelling == "l" and pending is not None and pending not in _AS_CODA:
                syllables.append(_syllable(pending, "ㅡ", "ㄹ"))
                short.append(False)
                # The l is this syllable's final, and also the next onset when a
                # vowel follows: 'flush' is 플러시, but 'apple' is 애플, not 애플르.
                follows = _match(_VOWEL_RULES, word, index + len(spelling))
                pending = "ㄹ" if follows else None
                index += len(spelling)
                continue
            flush_pending()
            pending = jamo
            index += len(spelling)
            continue
        index += 1
    flush_pending()
    return "".join(syllables)


def _has_no_coda(syllable: str) -> bool:
    code = ord(syllable) - 0xAC00
    return 0 <= code < 11172 and code % 28 == 0


def _with_coda(syllable: str, coda: str) -> str:
    return chr(ord(syllable) + _CODAS.index(coda))


def _spell_out(word: str) -> str:
    return "".join(LETTERS.get(character, character) for character in word.lower())


def say(word: str) -> str:
    """Return the Hangul a Korean speaker would say for one Latin token."""
    lowered = word.lower()
    if lowered in TERMS:
        return TERMS[lowered]
    if lowered in ACRONYM_WORDS:
        return ACRONYM_WORDS[lowered]
    # An acronym is read letter by letter; that is already the Korean convention.
    if word.isupper() and len(word) > 1:
        return _spell_out(word)
    # A plural keeps its stem's reading, acronyms included: CPUs is 씨피유스.
    # Checked before the camel split, which cannot tell CPUs from CP + Us.
    if lowered.endswith("s") and len(word) > 2:
        stem = word[:-1]
        base = TERMS.get(stem.lower()) or ACRONYM_WORDS.get(stem.lower())
        if base is None and stem.isupper() and len(stem) > 1:
            base = _spell_out(stem)
        if base is None and lowered.endswith("es"):
            base = TERMS.get(lowered[:-2])
        if base is not None:
            return f"{base}스"
    # An identifier spells its own parts: MyCPU is 마이씨피유, not one mangled word.
    parts = _CAMEL.findall(word)
    if len(parts) > 1:
        return "".join(say(part) for part in parts)
    if len(word) == 1:
        return LETTERS.get(lowered, word)
    return transliterate(word)


# A run of Latin letters, kept together with the marks that spell one term
# ('back-end', "don't"). Korean particles attach directly, so the boundary is
# the Latin script itself.
# Word boundaries inside an identifier: a capitalised word, a run of capitals,
# or a lower-case run.
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+")

LATIN_RUN = re.compile(r"[A-Za-z]+(?:[''’.\-/][A-Za-z]+)*")


def _say_run(match: re.Match[str]) -> str:
    return "".join(say(part) for part in re.split(r"[''’.\-/]", match.group(0)) if part)


def hangulize(text: str) -> str:
    """Replace every Latin-script term in ``text`` with its Korean reading."""
    return LATIN_RUN.sub(_say_run, text)
