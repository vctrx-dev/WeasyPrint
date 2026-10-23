"""Empty text must not introduce navigable PDF text elements."""

import re

import pytest

from weasyprint import HTML

from .testing_utils import FakeHTML, assert_no_logs


def _reachable_structure_objects(pdf):
    objects = {
        number: body for number, body in re.findall(
            rb'(\d+) 0 obj\s*(.*?)\s*endobj', pdf, re.DOTALL)}
    root = next(
        number for number, body in objects.items()
        if b'/Type /StructTreeRoot' in body)
    pending = [root]
    while pending:
        body = objects[pending.pop()]
        yield body
        children = re.search(rb'/K\s*\[(.*?)\]', body, re.DOTALL)
        if children:
            pending.extend(re.findall(rb'(\d+) 0 R', children.group(1)))


@assert_no_logs
@pytest.mark.parametrize('content', [
    '<span style="display:inline-block;width:100px;border-bottom:1px solid"></span>',
    '<span style="display:block;height:12px"></span>',
    '<span>&nbsp;</span>',
    '<span style="white-space:pre">   </span>',
    '<span>First</span> <span>Last</span>',
    '<span style="visibility:hidden">Hidden</span>',
])
def test_pdf_tags_omit_empty_text(content):
    pdf = FakeHTML(string=f'''
      <html lang="en"><title>Empty text</title><p>Name{content}</p>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    for body in _reachable_structure_objects(pdf):
        if re.search(rb'/S /Span(?:/|>>)', body):
            assert not re.search(rb'/K\s*\[\s*\]', body)
    for body in re.findall(
            rb'/Span\s*<<\s*/MCID\s+\d+\s*>>\s*BDC(.*?)EMC',
            pdf, re.DOTALL):
        assert re.search(rb'\b(?:TJ|Tj)\b', body)


@assert_no_logs
def test_pdf_tags_keep_blank_cells_and_control_state():
    pdf = HTML(string='''
      <html lang="en"><title>Blank fields</title>
      <table><tr><th scope="col">Name</th></tr><tr><td></td></tr></table>
      <label><input type="checkbox" checked>Selected</label>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert re.search(rb'/S /TD/K\s*\[\]', pdf)
    assert b'/PrintField' not in pdf
    assert b'/Alt (Selected, check box, checked)' in pdf
