from hashlib import sha256
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "output/research-2026-11-10"
SOURCE = REPORTS / "SKKU_Course_Agent_Model_Recommendation_v4.docx"
OUT = REPORTS / "SKKU_Course_Agent_Model_Recommendation_v5.docx"
SOURCE_HASH = "f5853d13620cb6098ed1832d2f39075b6de10c1d036dcd1f8cab1651349d1cbc"
assert sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_HASH

doc = Document(SOURCE)
body_text = [p.text for p in doc.paragraphs]
table_text = [[[c.text for c in r.cells] for r in t.rows] for t in doc.tables]
links = [(h.text, h.url) for p in doc.paragraphs for h in p.hyperlinks]


def remove(element, expression):
    for child in element.xpath(expression):
        child.getparent().remove(child)


def style(name, size, *, bold=False, before=0, after=6, line=1.2):
    if name not in doc.styles:
        doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        doc.styles[name].base_style = doc.styles["Normal"]
    result = doc.styles[name]
    result.font.name = "Times New Roman"
    result.font.size = Pt(size)
    result.font.color.rgb = RGBColor(0, 0, 0)
    result.font.bold = bold
    result.font.italic = False
    fonts = result.element.get_or_add_rPr().rFonts
    fonts.attrib.clear()
    for attr, family in (
        ("ascii", "Times New Roman"),
        ("hAnsi", "Times New Roman"),
        ("eastAsia", "Nanum Myeongjo"),
        ("cs", "Times New Roman"),
    ):
        fonts.set(qn(f"w:{attr}"), family)
    fmt = result.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = line
    return result


style("Normal", 11)
style("Title", 19, bold=True, after=8, line=1.07)
style("Heading 1", 15, bold=True, after=10, line=1.1)
style("Heading 2", 11.5, bold=True, before=9, after=5, line=1.1)
style("Summary References", 9.5, after=2, line=1.1)
style("Footer", 9, after=0, line=1)
style("Report Table Text", 10, after=0, line=1.05)
style("Report Table Caption", 10, bold=True, before=5, after=4, line=1.1)
doc.styles["Report Table Caption"].paragraph_format.keep_with_next = True

for element in (doc.styles.element, doc.element):
    remove(element, ".//w:pBdr | .//w:highlight")
    for color in element.xpath(".//w:color"):
        color.attrib.clear()
        color.set(qn("w:val"), "000000")
remove(doc.element, ".//w:rPr/w:rFonts | .//w:rPr/w:sz | .//w:rPr/w:szCs")

for index, para in enumerate(doc.paragraphs):
    if para.style.name == "Normal":
        for run in para.runs:
            run.bold = index == 2
    if not para.text.strip():
        para.paragraph_format.line_spacing = Pt(5)
        para.paragraph_format.space_before = Pt(0)
        para.paragraph_format.space_after = Pt(0)


def border(parent, name, width=0):
    edge = OxmlElement(f"w:{name}")
    edge.set(qn("w:val"), "single" if width else "nil")
    if width:
        edge.set(qn("w:sz"), str(width))
        edge.set(qn("w:color"), "333333")
    parent.append(edge)


captions = [
    "학교 서버 개발 실험",
    "Qwen과 Haiku의 공개 API 비교",
    "현재 API와 모델",
    "학교 서버 실험별 관측값",
    "공개 API 성능 비교 상세",
    "1인 월 토큰 사용량",
    "1,000명 월 토큰 사용량",
    "모델별 토큰 단가와 월 비용",
    "유료 모델 공개 벤치마크",
    "기능별 모델 구성",
    "구성별 1,000명 월 API 비용",
    "기능별 추가 비용",
]
numeric_columns = (
    {1}, {1, 2, 3}, set(), {1}, {1, 2, 3}, {1, 2, 3, 4}, {1, 2, 3},
    {1, 2, 3, 4}, {1, 2}, set(), {1, 2}, {2, 3},
)
assert len(doc.tables) == len(captions) == len(numeric_columns)
for number, (table, title, numbers) in enumerate(
    zip(doc.tables, captions, numeric_columns), 1
):
    caption = doc.add_paragraph(f"표 {number}. {title}", "Report Table Caption")
    table._tbl.addprevious(caption._p)

    table.style = doc.styles["Normal Table"]
    props = table._tbl.tblPr
    remove(table._tbl, ".//w:shd | .//w:tblBorders | .//w:tcBorders | .//w:tcMar")
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border(borders, edge, 6 if edge in ("top", "bottom") else 0)
    props.insert_element_before(borders, "w:tblLayout", "w:tblCellMar", "w:tblLook")

    for row_index, row in enumerate(table.rows):
        for column, cell in enumerate(row.cells):
            cell_props = cell._tc.get_or_add_tcPr()
            if row_index == 0:
                cell_borders = OxmlElement("w:tcBorders")
                border(cell_borders, "bottom", 4)
                cell_props.append(cell_borders)
            margins = OxmlElement("w:tcMar")
            for side in ("top", "left", "bottom", "right"):
                margin = OxmlElement(f"w:{side}")
                margin.set(qn("w:w"), "65" if side in ("top", "bottom") else "85")
                margin.set(qn("w:type"), "dxa")
                margins.append(margin)
            cell_props.append(margins)
            for para in cell.paragraphs:
                para.style = "Report Table Text"
                para.alignment = (
                    WD_ALIGN_PARAGRAPH.RIGHT if column in numbers
                    else WD_ALIGN_PARAGRAPH.LEFT
                )
                for run in para.runs:
                    run.bold = row_index == 0

for section in doc.sections:
    footer = section.footer.paragraphs[0]
    for run in footer.runs:
        run._r.getparent().remove(run._r)
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER

assert [p.text for p in doc.paragraphs if p.style.name != "Report Table Caption"] == body_text
assert [[[c.text for c in r.cells] for r in t.rows] for t in doc.tables] == table_text
assert [(h.text, h.url) for p in doc.paragraphs for h in p.hyperlinks] == links
assert not doc.element.xpath(".//w:tbl//w:shd")
assert {color.get(qn("w:val")) for color in doc.element.xpath(".//w:color")} == {"000000"}
doc.save(OUT)
assert sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_HASH
print(OUT)
print("PASS: body text, 12 tables, links and source file unchanged")
