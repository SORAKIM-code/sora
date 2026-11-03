"""표준 라이브러리만으로 .xlsx 를 읽고 쓴다 (외부 패키지 반입이 어려운 환경을 고려).

읽기: 공유 문자열·인라인 문자열·숫자·논리값 셀을 문자열로 돌려준다. 수식은 저장된 결과값을 읽는다.
쓰기: 모든 셀을 텍스트 형식으로 쓴다(엑셀이 '2018-01' 같은 값을 날짜로 바꾸지 않도록).
"""
import re
import zipfile
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"m": M, "r": R}

MAX_UNCOMPRESSED = 100 * 1024 * 1024
_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class XlsxError(Exception):
    pass


def col_letter(i):
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def col_index(ref):
    m = re.match(r"([A-Z]+)", ref or "")
    if not m:
        return None
    n = 0
    for ch in m.group(1):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _text(el):
    """<si>/<is> 안의 글자. 일본어 후리가나(rPh)는 제외한다."""
    parts = []
    t = el.find(f"{{{M}}}t")
    if t is not None:
        parts.append(t.text or "")
    for r in el.findall(f"{{{M}}}r"):
        rt = r.find(f"{{{M}}}t")
        if rt is not None:
            parts.append(rt.text or "")
    return "".join(parts)


def read_xlsx(path, max_rows=20000, max_cols=200):
    """{시트명: [(행 번호, [셀 문자열...]), ...]} 를 돌려준다. 빈 셀은 ''."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        raise XlsxError(f"엑셀(.xlsx) 파일을 열 수 없습니다: {e}")
    with z:
        if sum(i.file_size for i in z.infolist()) > MAX_UNCOMPRESSED:
            raise XlsxError("엑셀 파일이 너무 큽니다.")
        names = set(z.namelist())
        if "xl/workbook.xml" not in names:
            raise XlsxError("엑셀(.xlsx) 형식이 아닙니다. .xls 파일이면 엑셀에서 .xlsx 로 다시 저장하세요.")
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
                shared.append(_text(si))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        out = {}
        for s in ET.fromstring(z.read("xl/workbook.xml")).find("m:sheets", NS):
            target = rels.get(s.get(f"{{{R}}}id"), "")
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            if target not in names:
                continue
            out[s.get("name")] = _read_sheet(ET.fromstring(z.read(target)), shared, max_rows, max_cols)
        return out


def _read_sheet(root, shared, max_rows, max_cols):
    rows = []
    data = root.find("m:sheetData", NS)
    if data is None:
        return rows
    next_r = 1
    for row in data.findall("m:row", NS):
        rnum = int(row.get("r") or next_r)
        next_r = rnum + 1
        if len(rows) >= max_rows:
            raise XlsxError(f"행이 {max_rows}개를 넘습니다.")
        cells = {}
        next_c = 0
        for c in row.findall("m:c", NS):
            ci = col_index(c.get("r"))
            ci = next_c if ci is None else ci
            next_c = ci + 1
            if ci >= max_cols:
                continue
            t = c.get("t")
            v = c.find("m:v", NS)
            if t == "s":
                val = shared[int(v.text)] if v is not None and v.text else ""
            elif t == "inlineStr":
                is_ = c.find("m:is", NS)
                val = _text(is_) if is_ is not None else ""
            elif t == "b":
                val = "TRUE" if v is not None and v.text == "1" else "FALSE"
            else:
                val = v.text if v is not None and v.text is not None else ""
                if t is None and re.fullmatch(r"-?\d+\.0+", val):
                    val = val.split(".")[0]
            cells[ci] = val
        if cells:
            width = max(cells) + 1
            rows.append((rnum, [cells.get(i, "") for i in range(width)]))
    return rows


# ── 쓰기 ──
_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{M}">
<fonts count="3">
<font><sz val="11"/><name val="맑은 고딕"/><family val="2"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="맑은 고딕"/><family val="2"/></font>
<font><b/><sz val="11"/><name val="맑은 고딕"/><family val="2"/></font>
</fonts>
<fills count="4">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF1F3A5F"/><bgColor indexed="64"/></patternFill></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFB4472C"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="2">
<border><left/><right/><top/><bottom/><diagonal/></border>
<border><left style="thin"><color rgb="FFD0D5DD"/></left><right style="thin"><color rgb="FFD0D5DD"/></right><top style="thin"><color rgb="FFD0D5DD"/></top><bottom style="thin"><color rgb="FFD0D5DD"/></bottom><diagonal/></border>
</borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="5">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="49" fontId="1" fillId="2" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="49" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="49" fontId="1" fillId="3" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center" wrapText="1"/></xf>
<xf numFmtId="49" fontId="2" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

STYLE_HEADER, STYLE_BODY, STYLE_HEADER_REQUIRED, STYLE_BOLD = 1, 2, 3, 4


def _clean(s):
    return _ILLEGAL.sub("", str(s))


def _sheet_xml(sheet, shared_index):
    rows = sheet["rows"]
    styles = sheet.get("styles") or {}
    ncols = max((len(r) for r in rows), default=1)
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{M}" xmlns:r="{R}">']
    out.append(f'<dimension ref="A1:{col_letter(ncols - 1)}{max(len(rows), 1)}"/>')
    if sheet.get("freeze"):
        out.append('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                   '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>')
    else:
        out.append('<sheetViews><sheetView workbookViewId="0"/></sheetViews>')
    out.append('<sheetFormatPr defaultRowHeight="16.5"/>')
    widths = sheet.get("widths") or []
    if widths:
        out.append("<cols>" + "".join(
            f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1" style="{STYLE_BODY}"/>' for i, w in enumerate(widths)) + "</cols>")
    out.append("<sheetData>")
    for ri, row in enumerate(rows):
        cells = []
        for ci, val in enumerate(row):
            ref = f"{col_letter(ci)}{ri + 1}"
            st = styles.get((ri, ci), STYLE_HEADER if ri == 0 and sheet.get("header", True) else STYLE_BODY)
            if val is None or val == "":
                cells.append(f'<c r="{ref}" s="{st}"/>')
            elif shared_index is not None:
                idx = shared_index.setdefault(_clean(val), len(shared_index))
                cells.append(f'<c r="{ref}" s="{st}" t="s"><v>{idx}</v></c>')
            else:
                cells.append(f'<c r="{ref}" s="{st}" t="inlineStr"><is><t xml:space="preserve">{escape(_clean(val))}</t></is></c>')
        out.append(f'<row r="{ri + 1}">' + "".join(cells) + "</row>")
    out.append("</sheetData>")
    dv = sheet.get("validations") or []
    if dv:
        out.append(f'<dataValidations count="{len(dv)}">')
        for col, options in dv:
            letter = col_letter(col)
            formula = escape('"' + ",".join(options) + '"')
            out.append(f'<dataValidation type="list" allowBlank="1" showErrorMessage="1" sqref="{letter}2:{letter}5000">'
                       f'<formula1>{formula}</formula1></dataValidation>')
        out.append("</dataValidations>")
    out.append('<pageMargins left="0.7" right="0.7" top="0.75" bottom="0.75" header="0.3" footer="0.3"/></worksheet>')
    return "".join(out)


def write_xlsx(path, sheets, shared_strings=False):
    """sheets: [{"name", "rows": [[...]], "widths": [...], "freeze": bool, "validations": [(열, [값...])],
    "styles": {(행, 열): 스타일}}]"""
    shared_index = {} if shared_strings else None
    sheet_xml = [_sheet_xml(s, shared_index) for s in sheets]
    ct = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
          f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    for i in range(len(sheets)):
        ct.append(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    if shared_strings:
        ct.append('<Override PartName="/xl/sharedStrings.xml" '
                  'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>')
    ct.append("</Types>")
    wb = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{M}" xmlns:r="{R}"><sheets>']
    wb += [f'<sheet name="{escape(s["name"])}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, s in enumerate(sheets)]
    wb.append("</sheets></workbook>")
    rels = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PR}">']
    rels += [f'<Relationship Id="rId{i + 1}" Type="{R}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
             for i in range(len(sheets))]
    n = len(sheets)
    rels.append(f'<Relationship Id="rId{n + 1}" Type="{R}/styles" Target="styles.xml"/>')
    if shared_strings:
        rels.append(f'<Relationship Id="rId{n + 2}" Type="{R}/sharedStrings" Target="sharedStrings.xml"/>')
    rels.append("</Relationships>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "".join(ct))
        z.writestr("_rels/.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{PR}">'
                   f'<Relationship Id="rId1" Type="{R}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", "".join(wb))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        z.writestr("xl/styles.xml", _STYLES)
        for i, x in enumerate(sheet_xml):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", x)
        if shared_strings:
            items = sorted(shared_index.items(), key=lambda kv: kv[1])
            z.writestr("xl/sharedStrings.xml",
                       f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<sst xmlns="{M}" count="{len(items)}" uniqueCount="{len(items)}">'
                       + "".join(f'<si><t xml:space="preserve">{escape(s)}</t></si>' for s, _ in items) + "</sst>")
