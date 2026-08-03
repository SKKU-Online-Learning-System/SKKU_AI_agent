"""SAFE guardrails for the course agent.

Rule-based on purpose: the MVP needs predictable, reviewable behaviour, and the
service boundary lets an LLM moderation call replace the rules later. The rules
stay deliberately narrow so ordinary concept questions are never blocked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

CATEGORY_NORMAL = "normal"
CATEGORY_ASSIGNMENT = "assignment_direct_answer"
CATEGORY_EXAM = "exam_direct_answer"
CATEGORY_PRIVACY = "privacy_request"
CATEGORY_INJECTION = "prompt_injection"
CATEGORY_UNSAFE = "unsafe_content"

REDIRECT_HINT = "hint"

# Requests that only make sense as "do the graded work for me".
ASSIGNMENT_PATTERNS = (
    r"과제.{0,12}(전체|다|대신|통째로).{0,8}(짜|써|작성|해결|풀어)",
    r"(레포트|리포트|보고서|에세이).{0,12}(대신|전체|통째로).{0,8}(써|작성|만들)",
    r"제출용.{0,10}(코드|답안|보고서|과제)",
    r"(코드|답안).{0,8}전체.{0,8}(짜|작성|써)",
    r"do (my|the) (homework|assignment) for me",
    r"write (my|the) (report|essay|assignment) for me",
)
EXAM_PATTERNS = (
    r"(시험|중간고사|기말고사|퀴즈).{0,12}(정답|답).{0,8}(만|알려|골라|찍어)",
    r"(정답|답).{0,6}(번호|만).{0,8}(알려|골라|찍어)",
    r"give me (the )?(exam|quiz|test) answers",
)
PRIVACY_PATTERNS = (
    r"(다른|타).{0,4}(학생|사람|수강생).{0,12}(개인정보|학번|연락처|전화번호|이메일|주소|성적)",
    r"(교수님|교수자|조교).{0,10}(개인정보|연락처|전화번호|집주소|주민등록번호)",
    r"(학번|주민등록번호|전화번호).{0,10}(알려|조회|찾아)",
    r"(personal|contact) (info|information|details) of (another|other)",
)
INJECTION_PATTERNS = (
    r"(이전|위의|앞의).{0,6}(지시|명령|규칙).{0,8}(무시|잊)",
    r"시스템\s*프롬프트.{0,10}(보여|출력|알려|공개)",
    r"(내부|숨겨진).{0,6}(지시|규칙|프롬프트).{0,10}(공개|출력|알려)",
    r"ignore (all |the )?(previous|above) instructions",
    r"(show|reveal|print) (me )?(your |the )?system prompt",
    r"developer mode",
)
UNSAFE_PATTERNS = (
    r"(폭발물|사제폭탄|마약).{0,10}(제조|만드는|만들)",
    r"(해킹|디도스|랜섬웨어).{0,12}(방법|코드|만들|실행)",
    r"(자살|자해).{0,10}(방법|하는 법)",
    r"how to (make|build) (a )?(bomb|explosive)",
)

# Legitimate study requests that must survive the rules above.
ALLOWLIST_PATTERNS = (
    r"(개념|원리|정의|차이).{0,10}(설명|알려)",
    r"힌트",
    r"(오류|에러|버그).{0,10}(원인|이유|왜)",
    r"어떻게 접근",
    r"explain (the )?(concept|idea|difference)",
)


@dataclass(frozen=True)
class SafetyResult:
    blocked: bool
    category: str
    reason: Optional[str] = None
    redirect_type: Optional[str] = None
    safe_answer: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "category": self.category,
            "reason": self.reason,
            "redirect_type": self.redirect_type,
        }


NORMAL_RESULT = SafetyResult(blocked=False, category=CATEGORY_NORMAL)

BLOCK_ANSWERS = {
    CATEGORY_PRIVACY: (
        "다른 사용자의 개인정보는 제공할 수 없습니다. "
        "수업 관련 문의는 강의자료나 교수자 안내를 확인해 주세요."
    ),
    CATEGORY_INJECTION: (
        "내부 지시문이나 시스템 프롬프트는 공개할 수 없습니다. "
        "학습에 도움이 되는 질문을 해주시면 강의자료를 근거로 답변드릴게요."
    ),
    CATEGORY_UNSAFE: (
        "요청하신 내용은 교육 목적과 무관하거나 안전하지 않아 도와드릴 수 없습니다. "
        "수업 내용과 관련된 질문을 해주세요."
    ),
}


class SafetyGuardService:
    """Classifies a question and decides between answering, hinting, or refusing."""

    def check_question(self, question: str) -> SafetyResult:
        text = (question or "").strip().lower()
        if not text:
            return NORMAL_RESULT

        for category in (CATEGORY_INJECTION, CATEGORY_PRIVACY, CATEGORY_UNSAFE):
            if _matches(text, _patterns_for(category)):
                return SafetyResult(
                    blocked=True,
                    category=category,
                    reason=_reason_for(category),
                    safe_answer=BLOCK_ANSWERS[category],
                )

        if _matches(text, EXAM_PATTERNS):
            return SafetyResult(
                blocked=False,
                category=CATEGORY_EXAM,
                reason="시험 정답 직접 요청으로 판단됨",
                redirect_type=REDIRECT_HINT,
            )

        if _matches(text, ASSIGNMENT_PATTERNS) and not _matches(text, ALLOWLIST_PATTERNS):
            return SafetyResult(
                blocked=False,
                category=CATEGORY_ASSIGNMENT,
                reason="과제 전체 정답 요청으로 판단됨",
                redirect_type=REDIRECT_HINT,
            )

        return NORMAL_RESULT


def _patterns_for(category: str) -> tuple:
    return {
        CATEGORY_INJECTION: INJECTION_PATTERNS,
        CATEGORY_PRIVACY: PRIVACY_PATTERNS,
        CATEGORY_UNSAFE: UNSAFE_PATTERNS,
    }[category]


def _reason_for(category: str) -> str:
    return {
        CATEGORY_INJECTION: "시스템 프롬프트 탈취 시도로 판단됨",
        CATEGORY_PRIVACY: "개인정보 요청으로 판단됨",
        CATEGORY_UNSAFE: "안전하지 않은 요청으로 판단됨",
    }[category]


def _matches(text: str, patterns) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


HINT_SAFETY_NOTE = (
    "이 질문은 과제 또는 시험의 정답을 직접 요구하는 것으로 분류되었다. "
    "정답 전체를 제공하지 말고 개념과 단계별 힌트로 안내해라."
)
