from copy import deepcopy
from io import BytesIO
from pathlib import Path
from subprocess import check_output

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.table import Table


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (
    "8dd625a:output/research-2026-11-03/"
    "SKKU_API_Cost_Performance_Summary_2026-11-03_v3.docx"
)
OUT = ROOT / "output/research-2026-11-10/SKKU_Course_Agent_Model_Recommendation_v4.docx"
doc = Document(BytesIO(check_output(["git", "show", SOURCE], cwd=ROOT)))
paragraphs = doc.paragraphs
tables = doc.tables
body = doc.element.body
original = list(body)
table_values = [
    [[cell.text for cell in row.cells] for row in table.rows] for table in tables
]
ref_links = {
    link.text: deepcopy(link._element)
    for para in paragraphs
    for link in para.hyperlinks
}


def section(start, stop=None):
    first = original.index(paragraphs[start]._p)
    last = original.index(paragraphs[stop]._p) if stop is not None else len(original) - 1
    return original[first:last]


def append(*nodes):
    for node in nodes:
        body.insert_element_before(node, "w:sectPr")


def p(value, *, bold=False, refs=()):
    para = doc.add_paragraph()
    para.add_run(value).bold = bold
    for ref in refs:
        para.add_run(" ")
        para._p.append(deepcopy(ref_links[f"[{ref}]"]))
    return para


def heading(value, level=2, *, new_page=False):
    para = doc.add_heading(value, level)
    if new_page:
        para.paragraph_format.page_break_before = True
    return para


def brief_table(template, rows):
    table = Table(deepcopy(template._tbl), doc._body)
    for extra in list(table.rows)[len(rows):]:
        table._tbl.remove(extra._tr)
    for index, (row, values) in enumerate(zip(table.rows, rows)):
        for column, (cell, value) in enumerate(zip(row.cells, values)):
            para = cell.paragraphs[0]
            para.clear()
            para.alignment = (
                WD_ALIGN_PARAGRAPH.LEFT if column == 0 else WD_ALIGN_PARAGRAPH.CENTER
            )
            run = para.add_run(value)
            run.font.size = Pt(9.3)
            run.bold = index == 0
            run.font.color.rgb = RGBColor.from_string("FFFFFF" if index == 0 else "000000")
    append(table._tbl)
    spacer = doc.add_paragraph()
    spacer.paragraph_format.line_spacing = Pt(4)
    spacer.paragraph_format.space_after = Pt(0)


for node in original:
    if node.tag != qn("w:sectPr"):
        body.remove(node)

doc.core_properties.title = "SKKU Course Agent 모델 선택 요약"
doc.core_properties.subject = "현재 성능과 Haiku 적용 차이 및 추천 모델 구성"
doc.add_heading("SKKU Course Agent\n모델 선택 요약", level=0)
p("2026년 11월 10일 개정  |  공개 비교 및 비용 산정 기준 2026년 11월 3일")
p("추천안은 텍스트 답변에 Claude Haiku 5.5 medium을 시험하고, 실시간 음성과 자료 검색은 기존 Qwen으로 유지하는 구성이다.", bold=True)

heading("1 현재 Qwen 성능")
brief_table(tables[9], [
    ("현재 사용 모델", "학교 서버 개발 실험 p50", "측정 범위"),
    ("텍스트 Qwen3.8 27B", "4.58초", "생성 완료 비교 실험\n현재 텍스트 운영 실측 아님"),
    ("음성 Qwen3.5 9B", "응답 준비 7.30초\n첫 오디오 생성 10.02초", "강의자료 기반 준비 24턴\n첫 오디오는 합성 음성 3건"),
])
p("27B의 4.58초는 추론을 끈 동일 음성 정책 실험값이다. 9B의 첫 오디오 시간은 발화 종료 검출 후 생성까지이며, 브라우저 재생은 제외했다. 상세 조건은 부록 A에 정리했다.")

heading("2 Haiku 적용 시 성능과 비용 차이")
brief_table(tables[8], [
    ("공개 비교 지표", "Qwen3.8 27B\nxhigh", "Haiku 5.5\nmedium", "Haiku 적용 차이"),
    ("첫 답변까지 대기", "52.32초", "14.14초", "38.18초 단축"),
    ("답변 500토큰 출력 구간", "12.08초", "2.84초", "9.24초 단축"),
    ("전체 LLM 참고 시간", "64.40초", "16.98초", "47.42초 단축"),
    ("AA 지능 지수", "20", "25", "+5점"),
])
p("AA의 11월 3일 공개 비교에서 전체 시간은 약 74% 짧았다. 위 표는 학교 서버의 실제 단축 시간을 뜻하지 않는다.", refs=(25,))
p("1,000명 월 추가 API 비용: 1인 월 18회(중앙값) $14.40, 월 80회(기존 평균) $64. Qwen 단독의 외부 API 과금은 $0이며, 기존 서버 운영비는 두 구성에 공통이다.", bold=True, refs=(29,))

heading("3 추천 복합 구성")
p("텍스트 답변과 다음 힌트는 Haiku 5.5 medium, 실시간 음성 답변은 Qwen 9B를 사용한다. 자료 검색과 음성 인식 및 합성은 현재 구성을 유지하고, 학생 답 평가는 답변 생성에 포함해 별도 Sonnet 호출을 추가하지 않는다.")
p("같은 강의자료와 질문으로 한국어 답변의 근거 충실도와 힌트 품질, 지연을 확인한 뒤 채택한다. 사용량과 단가, 추가 기능 예산은 뒤의 부록을 참고한다.")

heading("부록 A 현재 API 구성과 학교 서버 실험", 1, new_page=True)
append(*section(3, 7)[1:])
heading("학교 서버 개발 실험의 측정 범위")
append(*section(65, 69)[1:])

heading("부록 B 공개 성능 비교의 측정 조건", 1, new_page=True)
p("AA의 2026년 11월 3일 조회값을 보존했다. 아래 비교는 약 10,000 입력 토큰과 답변 500토큰 조건이며, 비용 산정의 입력 4,000토큰과 청구 출력 800토큰 조건과 다르다. 연결된 평가 페이지의 수치는 조회 시점에 따라 갱신된다.", refs=(25, 27))
append(*section(61, 65)[1:])
append(*section(69, 71))

for start, stop, label in [
    (7, 20, "부록 C 중앙값과 평균 기준의 월 사용량"),
    (20, 31, "부록 D 모델별 1000명 월 API 비용"),
    (31, 36, "부록 E 유료 모델의 공개 성능 지표"),
    (49, 60, "부록 F 추천 구성의 비용 산정"),
    (36, 49, "부록 G 추가 기능의 별도 견적"),
    (71, None, "출처"),
]:
    nodes = section(start, stop)
    paragraphs[start].runs[0].text = label
    append(*nodes)

paragraphs[59].text = (
    "부록 B의 공개 지연과 품질은 별도 평가 조건이다. 위 예산에서 같은 성능이 "
    "보장되지 않는다. 부록 G의 $266.40 / $1,134.40은 Sonnet 별도 평가를 "
    "추가한 다른 견적이므로 이 장의 비용과 합산하지 않는다."
)
paragraphs[72].text = (
    "공개 성능과 비용표는 2026년 11월 3일 기준이다. 11월 10일 개정에서 "
    "모델 설정과 Haiku 단가를 재확인했다. 성능과 사용량은 새로 측정하지 않았다."
)
paragraphs[102].runs[0].text = "저장소 근거"
for para in paragraphs[103:107]:
    label, absolute_path = para.text.split("\n", 1)
    path = Path(absolute_path).relative_to(ROOT)
    para.clear()
    para.add_run(f"{label} {path.as_posix()}").font.size = Pt(9)
    para.paragraph_format.space_after = Pt(4)

for table, values in zip(tables, table_values):
    assert table._tbl.getparent() is body
    assert [[cell.text for cell in row.cells] for row in table.rows] == values
assert len(doc.tables) == len(tables) + 2
assert [para.text for para in doc.paragraphs if para.style.name == "Heading 2"][:3] == [
    "1 현재 Qwen 성능",
    "2 Haiku 적용 시 성능과 비용 차이",
    "3 추천 복합 구성",
]

OUT.parent.mkdir(parents=True, exist_ok=True)
doc.save(OUT)
print(OUT)
