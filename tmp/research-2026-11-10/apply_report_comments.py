from copy import deepcopy
from decimal import Decimal
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "output/research-2026-11-10"
SOURCE = REPORTS / "SKKU_Course_Agent_Model_Recommendation_v5.docx"
OUT = REPORTS / "SKKU_Course_Agent_Model_Recommendation_v6.docx"
doc = Document(SOURCE)
paragraphs = doc.paragraphs
tables = doc.tables
references = {
    h.text.split("]", 1)[0] + "]": h._element.get(qn("r:id"))
    for p in paragraphs
    for h in p.hyperlinks
}
references["[30]"] = doc.part.relate_to(
    "https://artificialanalysis.ai/models/qwen3-5-9b",
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
    is_external=True,
)


def edit(index, value, refs=()):
    para = paragraphs[index]
    para.clear()
    para.add_run(value)
    for number in refs:
        label = f"[{number}]"
        para.add_run(" ")
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), references[label])
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = label
        run.append(text)
        link.append(run)
        para._p.append(link)


def remove(index):
    para = paragraphs[index]._p
    para.getparent().remove(para)


def set_cell(cell, value, *, bold=False, right=False):
    para = cell.paragraphs[0]
    para.clear()
    para.alignment = WD_ALIGN_PARAGRAPH.RIGHT if right else WD_ALIGN_PARAGRAPH.LEFT
    para.add_run(value).bold = bold


def fill(table, values, *, numeric=()):
    assert len(table.rows) == len(values)
    for index, (row, line) in enumerate(zip(table.rows, values)):
        for column, (cell, value) in enumerate(zip(row.cells, line, strict=True)):
            set_cell(cell, value, bold=index == 0, right=column in numeric)


remove(2)
edit(1, "2026년 11월 10일 개정  |  Qwen 공개 평가 및 Haiku 적용 검토")
edit(3, "1. 사용 중인 모델(Qwen) 성능")
edit(4, "표 1. Qwen 공개 평가 결과")
fill(tables[0], [
    ("설정상 사용 모델", "공개 성능", "평가 기준"),
    ("텍스트 Qwen3.8 27B", "AA 지능 지수 20\n동급 비교군 중앙값 8", "Artificial Analysis\nxhigh 추론 설정"),
    ("음성 답변 Qwen3.5 9B", "MMLU-Pro 82.5%\nGPQA Diamond 81.7%", "Qwen 공식 모델 카드\n지식과 과학 추론 평가"),
])
edit(6, "두 행의 평가 기준은 서로 달라 점수를 직접 비교할 수 없다. 모두 공개 평가 결과이며, 학교 서버에서 실행해 성능을 측정한 값은 아니다.", (28, 21))

edit(8, "표 2. Qwen 대비 Haiku 성능과 월 API 비용")
comparison = tables[1]
set_cell(comparison.rows[0].cells[0], "비교 항목", bold=True)
assert Decimal("72") * Decimal("0.10") + Decimal("14.4") * Decimal("0.50") == Decimal("14.40")
assert Decimal("320") * Decimal("0.10") + Decimal("64") * Decimal("0.50") == Decimal("64")
for label, amount in [("월 API 비용 · 중앙값(18회)", "$14.40"), ("월 API 비용 · 기존 평균(80회)", "$64")]:
    comparison._tbl.append(deepcopy(comparison.rows[-1]._tr))
    for column, (cell, value) in enumerate(zip(comparison.rows[-1].cells, (label, "$0", amount, "+" + amount))):
        set_cell(cell, value, right=column > 0)
edit(10, "시간과 지수는 AA의 11월 3일 공개 API 비교값이다. 학교 환경의 실제 지연과는 다르다.", (25,))
edit(11, "비용은 월 활성 1,000명 기준이다. Qwen은 자체 서빙을 가정했으며 인프라비와 세금은 제외했다. 단가와 산식은 부록 F를 참고한다.")

edit(15, "부록 A 모델 설정과 공개 성능")
edit(16, "표 3. 코드에 설정된 API와 모델")
for row, model, performance in [
    (1, "외부 Model Server 연동\nQwen3.8-27B", "AA 지능 지수 20 (xhigh)"),
    (2, "외부 Model Server 연동\nQwen3.5-9B", "MMLU-Pro 82.5%\nGPQA Diamond 81.7%"),
]:
    set_cell(tables[2].rows[row].cells[1], model)
    set_cell(tables[2].rows[row].cells[2], performance)
edit(18, "코드의 기본 선택은 local_qwen과 local_cascade다. 이 표는 설정과 연동 대상이며, 학교 서버에 배포해 실행했다는 의미는 아니다. 자체 서빙 시 GPU와 서버 운영비는 별도다. [L1]", (20, 21, 22, 23))
edit(19, "27B는 AA의 동급 비교군 중앙값 8보다 높은 20점을 기록했다. 9B의 AA 지능 지수는 공개되지 않아 Qwen이 발표한 평가 점수를 인용했다. 두 결과는 한국어 수업 품질이나 음성 서비스 지연을 보여 주지 않는다.", (28, 30, 21))
edit(20, "공개 모델 사양")
edit(21, "표 4. Qwen 공개 사양과 지능 지수")
fill(tables[3], [
    ("항목", "Qwen3.8 27B", "Qwen3.5 9B"),
    ("파라미터 수", "27B", "9.7B"),
    ("공개 컨텍스트 길이", "256k 토큰", "262k 토큰"),
    ("AA 지능 지수", "20 (xhigh)", "미공개"),
])
edit(23, "공개 사양과 평가는 모델 및 공급자 조건을 기준으로 한다. 실제 배포에서 설정되는 컨텍스트 길이나 처리량은 달라질 수 있다.", (28, 30))
edit(24, "학교 서버의 텍스트 응답과 음성 지연은 측정하지 않았다. 도입 전에는 동일 자료로 검색, LLM, 음성 인식·합성 및 재생을 포함한 전체 시간을 측정한다.")

edit(73, "Haiku 단가는 100만 토큰당 입력 $0.10, 출력 $0.50이다. 중앙값은 72 × $0.10 + 14.4 × $0.50 = $14.40, 기존 평균은 320 × $0.10 + 64 × $0.50 = $64다. 회당 입력 4,000 및 청구 출력 800토큰을 가정했다.", (29,))
edit(85, "학생의 단순 동의를 이해로 잘못 판단하는 경우를 줄이고 오개념과 다음 힌트 단계를 점검하는 목적이다. Sonnet은 검증 후보이며, 개선 효과는 확인되지 않았다.", (2,))
edit(94, "Qwen 공개 평가는 2026년 11월 10일 확인했다. Haiku 비교와 다른 유료 모델 표는 11월 3일 기준이며, 학교 서버 성능과 사용자 트래픽은 측정하지 않았다.")
source = paragraphs[123].insert_paragraph_before("", "Summary References")
paragraphs[123]._p.addnext(source._p)
link = OxmlElement("w:hyperlink")
link.set(qn("r:id"), references["[30]"])
run = OxmlElement("w:r")
text = OxmlElement("w:t")
text.text = "[30] AA Qwen3.5 9B 공개 평가"
run.append(text)
link.append(run)
source._p.append(link)
remove(126)
remove(128)

all_text = "\n".join(doc.element.body.xpath(".//w:t/text()"))
assert all(s not in all_text for s in ("학교 서버 개발 실험", "4.58초", "3.054초", "4.583초", "7.296초", "10.017초", "[L2]", "[L4]"))
assert len(comparison.rows) == 7
assert len(doc.tables) == 12
doc.save(OUT)
print(OUT)
