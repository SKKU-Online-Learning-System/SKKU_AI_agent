from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "output/research-2026-11-10"
SOURCE = REPORTS / "SKKU_Course_Agent_Model_Recommendation_v6.docx"
OUT = REPORTS / "SKKU_Course_Agent_Model_Recommendation_v7.docx"
doc = Document(SOURCE)
paragraphs = doc.paragraphs
table = doc.tables[0]
other_tables = [t._tbl.xml for t in doc.tables[1:]]
references = {
    h.text.split("]", 1)[0] + "]": h._element.get(qn("r:id"))
    for p in paragraphs
    for h in p.hyperlinks
}


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


assert paragraphs[3].text == "표 1. Qwen 공개 평가 결과"
assert len(table.columns) == 3
table.add_column(Mm(23))
table.add_column(Mm(24))
widths = (34, 41, 25, 23, 47)
for column, width in zip(table.columns, widths, strict=True):
    column.width = Mm(width)

values = [
    ("설정상 사용 모델", "공개 평가 점수", "첫 답변 대기\n(초)", "출력 속도\n(토큰/초)", "공개 API 조건"),
    ("텍스트 답변\nQwen3.8 27B", "AA 지능 지수 20\n동급 중앙값 8", "117.15", "46", "Alibaba API\nxhigh 추론 설정"),
    ("음성 답변\nQwen3.5 9B", "MMLU-Pro 82.5%\nGPQA Diamond 81.7%", "38.35", "83", "추론형(Reasoning)\n측정 공급자 중앙값"),
]
for index, (row, line) in enumerate(zip(table.rows, values, strict=True)):
    base_props = deepcopy(row.cells[2]._tc.tcPr)
    for column, (cell, value, width) in enumerate(zip(row.cells, line, widths, strict=True)):
        if column >= 3:
            cell._tc.replace(cell._tc.tcPr, deepcopy(base_props))
        cell.width = Mm(width)
        para = cell.paragraphs[0]
        para.clear()
        para.style = "Report Table Text"
        para.alignment = WD_ALIGN_PARAGRAPH.RIGHT if column in (2, 3) else WD_ALIGN_PARAGRAPH.LEFT
        para.add_run(value).bold = index == 0

edit(3, "표 1. Qwen 공개 평가 점수와 응답 성능")
edit(5, "AA 공개 API의 최근 5일 집계값이다(11월 10일 조회). 첫 답변 대기는 추론을 포함하고, 출력 속도는 추론 토큰과 대기를 포함한 전체 요청 기준이다. 학교 서버나 음성 전체 실측은 아니다. 상세 조건은 부록 A 참고.", (27, 28, 30))
edit(9, "표 2는 11월 3일 공개 비교값이며, 표 1과 측정 방식이 다르다.", (25,))
edit(13, "같은 강의자료와 질문으로 근거 충실도, 힌트 품질, 지연을 검증한 뒤 채택한다.")

edit(22, "표 1은 AA Performance v3 기준이다. 약 1천·1만·10만 입력 토큰의 단일 요청과 다중 턴 과제를 동시 부하에서 시험한다. 측정된 작업 유형별 최근 5일 값을 같은 비중으로 평균한다. 27B는 Alibaba API, 9B는 측정 공급자의 중앙값이다.", (27, 28, 30))
edit(23, "첫 답변 대기는 요청부터 첫 답변 토큰까지의 시간이다. 출력 속도는 추론을 포함한 총 출력 토큰을 대기까지 포함한 요청 시간으로 나눈 값이다. 두 수치는 검색·음성 처리 시간을 포함하지 않는다. 표 2는 기존 500토큰 답변 조건의 비교여서 표 1과 직접 대조하지 않는다.", (27,))

assert [[cell.text for cell in row.cells] for row in table.rows] == [list(row) for row in values]
assert [t._tbl.xml for t in doc.tables[1:]] == other_tables
doc.save(OUT)
print(OUT)
