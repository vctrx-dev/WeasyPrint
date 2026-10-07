"""Logical placement for standalone text and illustrations."""

import re

import pytest

from .testing_utils import BASE_URL, FakeHTML, assert_no_logs


def structure(pdf):
    return {
        reference: body for reference, body in re.findall(
            rb'(\d+) 0 obj\s*(.*?)\s*endobj', pdf, re.DOTALL)
        if b'/Type /StructElem' in body}


@assert_no_logs
@pytest.mark.parametrize('container', ['div', 'main', 'section', 'article'])
def test_standalone_text_has_paragraph_container(container):
    pdf = FakeHTML(string=f'''
      <html lang="en"><title>Labels</title>
      <{container}>Certificate <span>No. 1404</span></{container}>
      <p>Normal <span>inline</span> text</p>
    ''').write_pdf(pdf_tags=True)
    objects = structure(pdf)
    for body in objects.values():
        if b'/S /Span' not in body:
            continue
        parent = re.search(rb'/P (\d+) 0 R', body).group(1)
        assert not re.search(
            rb'/S /(Div|Part|Sect|Art|Document)(?:/|>>)', objects[parent])
    assert sum(b'/S /P/' in body for body in objects.values()) == 2
    assert any(b'/S /Span/' in body for body in objects.values())


@assert_no_logs
@pytest.mark.parametrize(('content', 'placement'), [
    ('<div><img src="pattern.png" alt="Pattern"></div>', b'Block'),
    ('<p>Before <img src="pattern.png" alt="Pattern"> after</p>', b'Inline'),
    ('<p>Before <label><img src="pattern.png" alt="Pattern"></label> after</p>',
     b'Inline'),
    ('<div><label><img src="pattern.png" alt="Pattern"></label></div>', b'Block'),
    ('<div><img style="display:block" src="pattern.png" '
     'alt="Pattern"></div>', b'Block'),
])
def test_figure_declares_logical_placement(content, placement):
    pdf = FakeHTML(string=f'''
      <html lang="en"><title>Images</title>{content}
    ''', base_url=BASE_URL).write_pdf(pdf_tags=True)
    figures = [body for body in structure(pdf).values() if b'/S /Figure' in body]
    assert len(figures) == 1
    assert b'/Placement /' + placement in figures[0]
    assert b'/Alt (Pattern)' in figures[0]
    assert b'/BBox [' in figures[0]


@assert_no_logs
def test_implicit_paragraphs_preserve_block_boundaries_and_order():
    pdf = FakeHTML(string='''
      <html lang="en"><title>Mixed text</title>
      <div>Before <span>first</span><p>Middle</p>After <span>last</span></div>
    ''').write_pdf(pdf_tags=True)
    objects = structure(pdf)
    group = next(body for body in objects.values() if b'/S /Div/' in body)
    children = re.search(rb'/K \[(.*?)\]', group).group(1)
    references = re.findall(rb'(\d+) 0 R', children)
    assert len(references) == 3
    paragraph_ids = []
    def visit(reference):
        body = objects[reference]
        if b'/S /P/' in body:
            paragraph_ids.append(reference)
        kids = re.search(rb'/K \[(.*?)\]', body).group(1)
        for child in re.findall(rb'(\d+) 0 R', kids):
            visit(child)
    for reference in references:
        visit(reference)
    assert len(paragraph_ids) == 3
    content_ids = []
    def content(reference):
        kids = re.search(rb'/K \[(.*?)\]', objects[reference]).group(1)
        if b' R' in kids:
            for child in re.findall(rb'(\d+) 0 R', kids):
                content(child)
        else:
            content_ids.extend(int(number) for number in kids.split())
    for reference in paragraph_ids:
        content(reference)
    assert content_ids == [0, 1, 2, 3, 4]


@assert_no_logs
@pytest.mark.parametrize('container', ['div', 'p'])
def test_neutral_wrappers_preserve_text_container(container):
    pdf = FakeHTML(string=f'''
      <html lang="en"><title>Neutral wrappers</title>
      <{container}><label><abbr>Certificate <span>No. 1404</span>
      </abbr></label></{container}>
    ''').write_pdf(pdf_tags=True)
    objects = structure(pdf)
    for body in objects.values():
        if b'/S /Span/' not in body:
            continue
        parent = objects[re.search(rb'/P (\d+) 0 R', body).group(1)]
        while b'/S /NonStruct/' in parent:
            parent = objects[re.search(rb'/P (\d+) 0 R', parent).group(1)]
        assert not re.search(rb'/S /(Div|Part|Sect|Art|Document)(?:/|>>)', parent)
    assert sum(b'/S /P/' in body for body in objects.values()) == 1


@assert_no_logs
def test_neutral_wrappers_in_cells_keep_table_semantics():
    pdf = FakeHTML(string='''
      <html lang="en"><title>Cell labels</title>
      <table><tr><th><label>Heading</label></th></tr>
      <tr><td><label><abbr>Value</abbr></label></td></tr></table>
    ''').write_pdf(pdf_tags=True)
    objects = structure(pdf)
    assert not any(b'/S /P/' in body for body in objects.values())
    assert sum(b'/S /TH/' in body for body in objects.values()) == 1
    assert sum(b'/S /TD/' in body for body in objects.values()) == 1
