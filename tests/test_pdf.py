"""Test PDF-related code, including metadata, bookmarks and hyperlinks."""

import gc
import hashlib
import io
import re
from codecs import BOM_UTF16_BE

import pytest

from weasyprint import HTML, Attachment
from weasyprint.document import Document, DocumentMetadata
from weasyprint.text.fonts import FontConfiguration
from weasyprint.urls import path2url

from .testing_utils import FakeHTML, assert_no_logs, capture_logs, resource_path

# Top and right positions in points, rounded to the default float precision of
# 6 digits, a rendered by pydyf
TOP = round(297 * 72 / 25.4, 6)
RIGHT = round(210 * 72 / 25.4, 6)


@assert_no_logs
@pytest.mark.parametrize('zoom', [1, 1.5, 0.5])
def test_page_size_zoom(zoom):
    pdf = FakeHTML(string='<style>@page{size:3in 4in').write_pdf(zoom=zoom)
    width, height = int(216 * zoom), int(288 * zoom)
    assert f'/MediaBox [0 0 {width} {height}]'.encode() in pdf


@assert_no_logs
def test_bookmarks_1():
    pdf = FakeHTML(string='''
      <h1>a</h1>  #
      <h4>b</h4>  ####
      <h3>c</h3>  ###
      <h2>d</h2>  ##
      <h1>e</h1>  #
    ''').write_pdf()
    # a
    # |_ b
    # |_ c
    # L_ d
    # e
    assert re.findall(b'/Count ([0-9-]*)', pdf)[-1] == b'5'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [
        b'a', b'b', b'c', b'd', b'e']


@assert_no_logs
def test_bookmarks_2():
    pdf = FakeHTML(string='<body>').write_pdf()
    assert b'Outlines' not in pdf


@assert_no_logs
def test_bookmarks_3():
    pdf = FakeHTML(string='<h1>a nbsp…</h1>').write_pdf()
    assert re.findall(b'/Title <(\\w*)>', pdf) == [
        b'feff006100a0006e0062007300702026']


@assert_no_logs
def test_bookmarks_4():
    pdf = FakeHTML(string='''
      <style>
        h1, h2, h3, span { height: 90pt; margin: 0 0 10pt 0 }
      </style>
      <h1>1</h1>
      <h1>2</h1>
      <h2 style="position: relative; left: 20pt">3</h2>
      <h2>4</h2>
      <h3>5</h3>
      <span style="display: block; page-break-before: always"></span>
      <h2>6</h2>
      <h1>7</h1>
      <h2>8</h2>
      <h3>9</h3>
      <h1>10</h1>
      <h2>11</h2>
    ''').write_pdf()
    # 1
    # 2
    # |_ 3
    # |_ 4
    # |  L_ 5
    # L_ 6
    # 7
    # L_ 8
    #    L_ 9
    # 10
    # L_ 11
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [
        str(i).encode() for i in range(1, 12)]
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    counts.pop(0)  # Page count
    outlines = counts.pop()
    assert outlines == b'11'
    assert counts == [
        b'0', b'4', b'0', b'1', b'0', b'0', b'2', b'1', b'0', b'1', b'0']


@assert_no_logs
def test_bookmarks_5():
    pdf = FakeHTML(string='''
      <h2>1</h2> level 1
      <h4>2</h4> level 2
      <h2>3</h2> level 1
      <h3>4</h3> level 2
      <h4>5</h4> level 3
    ''').write_pdf()
    # 1
    # L_ 2
    # 3
    # L_ 4
    #    L_ 5
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [
        str(i).encode() for i in range(1, 6)]
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    counts.pop(0)  # Page count
    outlines = counts.pop()
    assert outlines == b'5'
    assert counts == [b'1', b'0', b'2', b'1', b'0']


@assert_no_logs
def test_bookmarks_6():
    pdf = FakeHTML(string='''
      <h2>1</h2> h2 level 1
      <h4>2</h4> h4 level 2
      <h3>3</h3> h3 level 2
      <h5>4</h5> h5 level 3
      <h1>5</h1> h1 level 1
      <h2>6</h2> h2 level 2
      <h2>7</h2> h2 level 2
      <h4>8</h4> h4 level 3
      <h1>9</h1> h1 level 1
    ''').write_pdf()
    # 1
    # |_ 2
    # L_ 3
    #    L_ 4
    # 5
    # |_ 6
    # L_ 7
    #    L_ 8
    # 9
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [
        str(i).encode() for i in range(1, 10)]
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    counts.pop(0)  # Page count
    outlines = counts.pop()
    assert outlines == b'9'
    assert counts == [b'3', b'0', b'1', b'0', b'3', b'0', b'1', b'0', b'0']


@assert_no_logs
def test_bookmarks_7():
    # Reference for the next test. zoom=1
    pdf = FakeHTML(string='<h2>a</h2>').write_pdf()

    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'a']
    dest, = re.findall(b'/Dest \\[(.*)\\]', pdf)
    y = round(float(dest.strip().split()[-2]))

    pdf = FakeHTML(string='<h2>a</h2>').write_pdf(zoom=1.5)
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'a']
    dest, = re.findall(b'/Dest \\[(.*)\\]', pdf)
    assert round(float(dest.strip().split()[-2])) == 1.5 * y


@assert_no_logs
def test_bookmarks_8():
    pdf = FakeHTML(string='''
      <h1>a</h1>
      <h2>b</h2>
      <h3>c</h3>
      <h2 style="bookmark-state: closed">d</h2>
      <h3>e</h3>
      <h4>f</h4>
      <h1>g</h1>
    ''').write_pdf()
    # a
    # |_ b
    # |  |_ c
    # |_ d (closed)
    # |  |_ e
    # |     |_ f
    # g
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [
        b'a', b'b', b'c', b'd', b'e', b'f', b'g']
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    counts.pop(0)  # Page count
    outlines = counts.pop()
    assert outlines == b'5'
    assert counts == [b'3', b'1', b'0', b'-2', b'1', b'0', b'0']


@assert_no_logs
def test_bookmarks_9():
    pdf = FakeHTML(string='''
      <h1 style="bookmark-label: 'h1 on page ' counter(page)">a</h1>
    ''').write_pdf()
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    outlines = counts.pop()
    assert outlines == b'1'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'h1 on page 1']


@assert_no_logs
def test_bookmarks_10():
    pdf = FakeHTML(string='''
      <style>
      div:before, div:after {
         content: '';
         bookmark-level: 1;
         bookmark-label: 'x';
      }
      </style>
      <div>a</div>
    ''').write_pdf()
    # x
    # x
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    outlines = counts.pop()
    assert outlines == b'2'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'x', b'x']


@assert_no_logs
def test_bookmarks_11():
    pdf = FakeHTML(string='''
      <div style="display:inline; white-space:pre;
       bookmark-level:1; bookmark-label:'a'">
      a
      a
      a
      </div>
      <div style="bookmark-level:1; bookmark-label:'b'">
        <div>b</div>
        <div style="break-before:always">c</div>
      </div>
    ''').write_pdf()
    # a
    # b
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    outlines = counts.pop()
    assert outlines == b'2'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'a', b'b']


@assert_no_logs
def test_bookmarks_12():
    pdf = FakeHTML(string='''
      <div style="bookmark-level:1; bookmark-label:contents">a</div>
    ''').write_pdf()
    # a
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    outlines = counts.pop()
    assert outlines == b'1'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'a']


@assert_no_logs
def test_bookmarks_13():
    pdf = FakeHTML(string='''
      <div style="bookmark-level:1; bookmark-label:contents;
                  text-transform:uppercase">a</div>
    ''').write_pdf()
    # a
    counts = re.findall(b'/Count ([0-9-]*)', pdf)
    outlines = counts.pop()
    assert outlines == b'1'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'a']


@assert_no_logs
def test_bookmarks_14():
    pdf = FakeHTML(string='''
      <h1>a</h1>
      <h1> b c d </h1>
      <h1> e
             f </h1>
      <h1> g <span> h </span> i </h1>
    ''').write_pdf()
    assert re.findall(b'/Count ([0-9-]*)', pdf)[-1] == b'4'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [
        b'a', b'b c d', b'e f', b'g h i']


@assert_no_logs
def test_bookmarks_15():
    # Regression test for #1815.
    pdf = FakeHTML(string='''
      <style>@page { size: 10pt 10pt }</style>
      <h1>a</h1>
    ''').write_pdf()
    assert re.findall(b'/Count ([0-9-]*)', pdf)[-1] == b'1'
    assert re.findall(b'/Title \\((.*)\\)', pdf) == [b'a']
    assert b'/XYZ 0 10 0' in pdf


@assert_no_logs
def test_links_none():
    pdf = FakeHTML(string='<body>').write_pdf()
    assert b'Annots' not in pdf


@assert_no_logs
def test_links():
    pdf = FakeHTML(string='''
      <style>
        body { margin: 0; font-size: 10pt; line-height: 2 }
        p { display: block; height: 90pt; margin: 0 0 10pt 0 }
        img { width: 30pt; vertical-align: top }
      </style>
      <p><a href=" https://weasy\nprint.org\t"><img src=pattern.png></a></p>
      <p style="padding: 0 10pt"><a
         href="#lipsum"><img style="border: solid 1pt"
                             src=pattern.png></a></p>
      <p id=hello>Hello, World</p>
      <p id=lipsum>
        <a style="display: block; page-break-before: always; height: 30pt"
           href="#hel%6Co"></a>a
      </p>
    ''', base_url=resource_path('<inline HTML>')).write_pdf()

    uris = re.findall(b'/URI \\((.*)\\)', pdf)
    types = re.findall(b'/S (/\\w*)', pdf)
    subtypes = re.findall(b'/Subtype (/\\w*)', pdf)
    rects = [
        [float(number) for number in match.split()] for match in re.findall(
            b'/Rect \\[([\\d\\.]+ [\\d\\.]+ [\\d\\.]+ [\\d\\.]+)\\]', pdf)]

    # 30pt wide (like the image), 20pt high (like line-height)
    assert uris.pop(0) == b'https://weasyprint.org'
    assert subtypes.pop(0) == b'/Link'
    assert types.pop(0) == b'/URI'
    assert rects.pop(0) == [0, TOP, 30, TOP - 20]

    # The image itself: 30*30pt
    assert uris.pop(0) == b'https://weasyprint.org'
    assert subtypes.pop(0) == b'/Link'
    assert types.pop(0) == b'/URI'
    assert rects.pop(0) == [0, TOP, 30, TOP - 30]

    # 32pt wide (image + 2 * 1pt of border), 20pt high
    assert subtypes.pop(0) == b'/Link'
    assert b'/Dest (lipsum)' in pdf
    link = re.search(
        b'\\(lipsum\\) \\[\\d+ 0 R /XYZ ([\\d\\.]+ [\\d\\.]+ [\\d\\.]+)]',
        pdf).group(1)
    assert [float(number) for number in link.split()] == [0, TOP, 0]
    assert rects.pop(0) == [10, TOP - 100, 10 + 32, TOP - 100 - 20]

    # The image itself: 32*32pt
    assert subtypes.pop(0) == b'/Link'
    assert rects.pop(0) == [10, TOP - 100, 10 + 32, TOP - 100 - 32]

    # 100% wide (block), 30pt high
    assert subtypes.pop(0) == b'/Link'
    assert b'/Dest (hello)' in pdf
    link = re.search(
        b'\\(hello\\) \\[\\d+ 0 R /XYZ ([\\d\\.]+ [\\d\\.]+ [\\d\\.]+)]',
        pdf).group(1)
    assert [float(number) for number in link.split()] == [0, TOP - 200, 0]
    assert rects.pop(0) == [0, TOP, RIGHT, TOP - 30]


@assert_no_logs
def test_sorted_links():
    # Regression test for #1352.
    pdf = FakeHTML(string='''
      <p id="zzz">zzz</p>
      <p id="aaa">aaa</p>
      <a href="#zzz">z</a>
      <a href="#aaa">a</a>
    ''', base_url=resource_path('<inline HTML>')).write_pdf()
    assert b'(zzz) [' in pdf.split(b'(aaa) [')[-1]


@assert_no_logs
def test_relative_links_no_height():
    # 100% wide (block), 0pt high
    pdf = FakeHTML(
        string='<a href="../lipsum" style="display: block"></a>a',
        base_url='https://weasyprint.org/foo/bar/').write_pdf()
    assert b'/S /URI\n/URI (https://weasyprint.org/foo/lipsum)'
    assert f'/Rect [0 {TOP} {RIGHT} {TOP}]'.encode() in pdf


@assert_no_logs
def test_relative_links_missing_base():
    # Relative URI reference without a base URI
    pdf = FakeHTML(
        string='<a href="../lipsum" style="display: block"></a>a',
        base_url=None).write_pdf()
    assert b'/S /URI\n/URI (../lipsum)'
    assert f'/Rect [0 {TOP} {RIGHT} {TOP}]'.encode() in pdf


@assert_no_logs
def test_relative_links_internal():
    # Internal URI reference without a base URI: OK
    pdf = FakeHTML(
        string='<a href="#lipsum" id="lipsum" style="display: block"></a>a',
        base_url=None).write_pdf()
    assert b'/Dest (lipsum)' in pdf
    link = re.search(
        b'\\(lipsum\\) \\[\\d+ 0 R /XYZ ([\\d\\.]+ [\\d\\.]+ [\\d\\.]+)]',
        pdf).group(1)
    assert [float(number) for number in link.split()] == [0, TOP, 0]
    rect = re.search(
        b'/Rect \\[([\\d\\.]+ [\\d\\.]+ [\\d\\.]+ [\\d\\.]+)\\]',
        pdf).group(1)
    assert [float(number) for number in rect.split()] == [0, TOP, RIGHT, TOP]


@assert_no_logs
def test_relative_links_anchors():
    pdf = FakeHTML(
        string='<a href="#lipsum" id="lipsum" style="display: block"></a>a',
        base_url=None).write_pdf()
    assert b'/Dest (lipsum)' in pdf
    link = re.search(
        b'\\(lipsum\\) \\[\\d+ 0 R /XYZ ([\\d\\.]+ [\\d\\.]+ [\\d\\.]+)]',
        pdf).group(1)
    assert [float(number) for number in link.split()] == [0, TOP, 0]
    rect = re.search(
        b'/Rect \\[([\\d\\.]+ [\\d\\.]+ [\\d\\.]+ [\\d\\.]+)\\]',
        pdf).group(1)
    assert [float(number) for number in rect.split()] == [0, TOP, RIGHT, TOP]


@assert_no_logs
def test_relative_links_different_base():
    pdf = FakeHTML(
        string='<a href="/test/lipsum"></a>a',
        base_url='https://weasyprint.org/foo/bar/').write_pdf()
    assert b'https://weasyprint.org/test/lipsum' in pdf


@assert_no_logs
def test_relative_links_same_base():
    pdf = FakeHTML(
        string='<a id="test" href="/foo/bar/#test"></a>a',
        base_url='https://weasyprint.org/foo/bar/').write_pdf()
    assert b'/Dest (test)' in pdf


@assert_no_logs
def test_missing_links():
    with capture_logs() as logs:
        pdf = FakeHTML(string='''
          <style> a { display: block; height: 15pt } </style>
          <a href="#lipsum"></a>
          <a href="#missing" id="lipsum"></a>
          <a href=""></a>a
        ''', base_url=None).write_pdf()
    assert b'/Dest (lipsum)' in pdf
    assert len(logs) == 1
    link = re.search(
        b'\\(lipsum\\) \\[\\d+ 0 R /XYZ ([\\d\\.]+ [\\d\\.]+ [\\d\\.]+)]',
        pdf).group(1)
    assert [float(number) for number in link.split()] == [0, TOP - 15, 0]
    rect = re.search(
        b'/Rect \\[([\\d\\.]+ [\\d\\.]+ [\\d\\.]+ [\\d\\.]+)\\]',
        pdf).group(1)
    assert [float(number) for number in rect.split()] == [
        0, TOP, RIGHT, TOP - 15]
    assert 'ERROR: No anchor #missing for internal URI reference' in logs[0]


@assert_no_logs
def test_anchor_multiple_pages():
    pdf = FakeHTML(string='''
      <style> a { display: block; break-after: page } </style>
      <div id="lipsum">
        <a href="#lipsum"></a>
        <a href="#lipsum"></a>
        <a href="#lipsum"></a>
      </div>
    ''', base_url=None).write_pdf()
    first_page, = re.findall(b'/Kids \\[(\\d+) 0 R', pdf)
    assert b'/Names [(lipsum) [' + first_page in pdf


@assert_no_logs
def test_embed_gif():
    assert b'/Filter /DCTDecode' not in FakeHTML(
        base_url=resource_path('dummy.html'),
        string='<img src="pattern.gif">').write_pdf()


@assert_no_logs
def test_embed_jpeg():
    # JPEG-encoded image, embedded in PDF:
    assert b'/Filter /DCTDecode' in FakeHTML(
        base_url=resource_path('dummy.html'),
        string='<img src="blue.jpg">').write_pdf()


@assert_no_logs
def test_embed_image_once():
    # Image repeated multiple times, embedded once
    assert FakeHTML(
        base_url=resource_path('dummy.html'),
        string='''
          <img src="blue.jpg">
          <div style="background: url(blue.jpg)"></div>
          <img src="blue.jpg">
          <div style="background: url(blue.jpg) no-repeat"></div>
        ''').write_pdf().count(b'/Filter /DCTDecode') == 1


@assert_no_logs
def test_embed_images_from_pages():
    page1, = FakeHTML(
        base_url=resource_path('dummy.html'),
        string='<img src="blue.jpg">').render().pages
    page2, = FakeHTML(
        base_url=resource_path('dummy.html'),
        string='<img src="not-optimized.jpg">').render().pages
    document = Document(
        (page1, page2), metadata=DocumentMetadata(),
        font_config=FontConfiguration(), color_profiles={},
        url_fetcher=None, output_intent=None).write_pdf()
    assert document.count(b'/Filter /DCTDecode') == 2


@assert_no_logs
def test_document_info():
    pdf = FakeHTML(string='''
      <meta name=author content="I Me &amp; Myself">
      <title>Test document</title>
      <h1>Another title</h1>
      <meta name=generator content="Human after all">
      <meta name=keywords content="html ,\tcss,
                                   pdf,css">
      <meta name=description content="Blah… ">
      <meta name=dcterms.created content=2011-04-21T23:00:00Z>
      <meta name=dcterms.modified content=2013-07-21T23:46+01:00>
    ''').write_pdf()
    assert b'/Author (I Me & Myself)' in pdf
    assert b'/Title (Test document)' in pdf
    assert (
        b'/Creator <feff00480075006d0061006e00a00061'
        b'006600740065007200a00061006c006c>') in pdf
    assert b'/Keywords (html, css, pdf)' in pdf
    assert b'/Subject <feff0042006c0061006820260020>' in pdf
    assert b'/CreationDate (D:20110421230000Z)' in pdf
    assert b"/ModDate (D:20130721234600+01'00)" in pdf


@assert_no_logs
def test_embedded_files_attachments(tmp_path):
    absolute_tmp_path = tmp_path / 'some_file.txt'
    absolute_data = b'12345678'
    absolute_tmp_path.write_bytes(absolute_data)
    absolute_url = path2url(absolute_tmp_path)
    assert absolute_url.startswith('file://')

    relative_tmp_path = tmp_path / 'äöü.txt'
    relative_data = b'abcdefgh'
    relative_tmp_path.write_bytes(relative_data)

    pdf = FakeHTML(
        string=f'''
          <title>Test document</title>
          <meta charset="utf-8">
          <link
            rel="attachment"
            title="some file attachment äöü"
            href="
              data:,hi%20there
            ">
          <link rel="attachment" href="{absolute_url}">
          <link rel="attachment" href="{relative_tmp_path.name}">
          <h1>Heading 1</h1>
          <h2>Heading 2</h2>
        ''',
        base_url=tmp_path,
    ).write_pdf(
        attachments=[
            Attachment('data:,oob attachment', description='Hello'),
            'data:,raw URL',
            io.BytesIO(b'file like obj')
        ]
    )
    assert f'<{hashlib.md5(b"hi there").hexdigest()}>'.encode() in pdf
    assert b'/F (attachment.bin)' in pdf
    assert b'/UF (attachment.bin)' in pdf
    name = BOM_UTF16_BE + 'some file attachment äöü'.encode('utf-16-be')
    assert b'/Desc <' + name.hex().encode() + b'>' in pdf

    assert hashlib.md5(absolute_data).hexdigest().encode() in pdf
    assert absolute_tmp_path.name.encode() in pdf

    assert hashlib.md5(relative_data).hexdigest().encode() in pdf
    name = BOM_UTF16_BE + 'some file attachment äöü'.encode('utf-16-be')
    assert b'/Desc <' + name.hex().encode() + b'>' in pdf

    assert hashlib.md5(b'oob attachment').hexdigest().encode() in pdf
    assert b'/Desc (Hello)' in pdf
    assert hashlib.md5(b'raw URL').hexdigest().encode() in pdf
    assert hashlib.md5(b'file like obj').hexdigest().encode() in pdf

    assert b'/EmbeddedFiles' in pdf
    assert b'/Outlines' in pdf


@assert_no_logs
def test_attachments_data():
    pdf = FakeHTML(string='''
      <title>Test document 2</title>
      <meta charset="utf-8">
      <link rel="attachment" href="data:,some data">
    ''').write_pdf()
    md5 = f'<{hashlib.md5(b"some data").hexdigest()}>'.encode()
    assert md5 in pdf
    assert b'EmbeddedFiles' in pdf


@assert_no_logs
def test_attachments_data_with_anchor():
    pdf = FakeHTML(string='''
      <title>Test document 2</title>
      <meta charset="utf-8">
      <link rel="attachment" href="data:,some data">
      <h1 id="title">Title</h1>
      <a href="#title">example</a>
    ''').write_pdf()
    md5 = f'<{hashlib.md5(b"some data").hexdigest()}>'.encode()
    assert md5 in pdf
    assert b'EmbeddedFiles' in pdf


@assert_no_logs
def test_attachments_no_href():
    with capture_logs() as logs:
        pdf = FakeHTML(string='''
          <title>Test document 2</title>
          <meta charset="utf-8">
          <link rel="attachment">
        ''').write_pdf()
    assert b'Names' not in pdf
    assert b'Outlines' not in pdf
    assert len(logs) == 1
    assert 'Missing href' in logs[0]


@assert_no_logs
def test_attachments_none():
    pdf = FakeHTML(string='''
      <title>Test document 3</title>
      <meta charset="utf-8">
      <h1>Heading</h1>
    ''').write_pdf()
    assert b'Names' not in pdf
    assert b'Outlines' in pdf


@assert_no_logs
def test_attachments_none_empty():
    pdf = FakeHTML(string='''
      <title>Test document 3</title>
      <meta charset="utf-8">
    ''').write_pdf()
    assert b'Names' not in pdf
    assert b'Outlines' not in pdf


@assert_no_logs
def test_annotations():
    pdf = FakeHTML(string='''
      <title>Test document</title>
      <meta charset="utf-8">
      <a
        download="test.txt"
        rel="attachment"
        href="data:,some data"
      >A link that lets you download an attachment</a>
    ''').write_pdf()

    assert hashlib.md5(b'some data').hexdigest().encode() in pdf
    assert b'/FileAttachment' in pdf
    assert b'/EmbeddedFiles' not in pdf
    assert b'test.txt' in pdf


@assert_no_logs
def test_annotations_base64():
    pdf = FakeHTML(string='''
      <title>Test document</title>
      <meta charset="utf-8">
      <a
        rel="attachment"
        href="data:text/plain;base64,c3VwZXI="
        download>A link that lets you download an attachment</a>
    ''').write_pdf()

    assert hashlib.md5(b'super').hexdigest().encode() in pdf
    assert b'/FileAttachment' in pdf
    assert b'/EmbeddedFiles' not in pdf
    assert b'c3VwZXI=' not in pdf
    assert b'attachment.bin' in pdf


@pytest.mark.parametrize(('style', 'media', 'bleed', 'trim'), [
    ('bleed: 30pt; size: 10pt',
     [-30, -30, 40, 40],
     [-10, -10, 20, 20],
     [0, 0, 10, 10]),
    ('bleed: 15pt 3pt 6pt 18pt; size: 12pt 15pt',
     [-18, -15, 15, 21],
     [-10, -10, 15, 21],
     [0, 0, 12, 15]),
])
@assert_no_logs
def test_bleed(style, media, bleed, trim):
    pdf = FakeHTML(string='''
      <title>Test document</title>
      <style>@page { %s }</style>
      <body>test
    ''' % style).write_pdf()
    assert f'/MediaBox {str(media).replace(",", "")}'.encode() in pdf
    assert f'/BleedBox {str(bleed).replace(",", "")}'.encode() in pdf
    assert f'/TrimBox {str(trim).replace(",", "")}'.encode() in pdf


@assert_no_logs
def test_default_rdf_metadata():
    pdf_document = FakeHTML(string='<body>test</body>').render()

    pdf_document.metadata.title = None

    pdf_bytes = pdf_document.write_pdf(
        pdf_variant='pdf/a-3b', pdf_identifier=b'example-bytes', uncompressed_pdf=True)
    assert b'<rdf:RDF xmlns:pdf="http://ns.adobe.com/pdf/1.3/"' in pdf_bytes


@assert_no_logs
def test_custom_rdf_metadata():
    def generate_rdf_metadata(*args, **kwargs):
        return b'TEST_METADATA'

    pdf_document = FakeHTML(string='<body>test</body>').render()

    pdf_document.metadata.title = None
    pdf_document.metadata.generate_rdf_metadata = generate_rdf_metadata

    pdf_bytes = pdf_document.write_pdf(
        pdf_variant='pdf/a-3b', pdf_identifier=b'example-bytes', uncompressed_pdf=True)
    assert b'TEST_METADATA' in pdf_bytes


@assert_no_logs
def test_color_spaces_with_icc_output_intent():
    shading_pdf = FakeHTML(string='''
      <style>html { background: linear-gradient(red, blue) }</style>
    ''').write_pdf(output_intent='srgb')
    group_pdf = FakeHTML(string='''
      <div style="width: 1px; height: 1px; background: red; opacity: .5"></div>
    ''').write_pdf(output_intent='srgb')

    profile = rb'\[/ICCBased \d+ 0 R\]'
    assert re.search(rb'/ShadingType 2/ColorSpace ' + profile, shading_pdf)
    assert re.search(rb'/Group <<[^>]+/CS ' + profile, group_pdf)


@assert_no_logs
def test_font_descent_ascent():
    pdf = FakeHTML(string='''
      <html style="font-family: weasyprint">abc
    ''').write_pdf()
    assert b'/Descent -200' in pdf
    assert b'/Ascent 800' in pdf


@assert_no_logs
def test_pdf_tags_inline_table():
    # Regression test for #2601.
    FakeHTML(string='''
      <html lang="en"><table style="display: inline"><td>abc
    ''').write_pdf(pdf_tags=True)


@assert_no_logs
def test_pdf_tags_anonymous_table_cells():
    # Regression test for #2726.
    pdf = FakeHTML(string='''
      <html lang="en"><table><tr><th>a<div>b</th><td>a<p>b</p>
    ''').write_pdf(pdf_tags=True)
    assert pdf.count(b'/TH') == 1
    assert pdf.count(b'/TD') == 1


def _pdf_structure_objects(pdf):
    return {
        b'%s 0 R' % reference: body
        for reference, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}


def _assert_table_cells_are_row_children(pdf, expected_count):
    """Return table cell elements and ensure anonymous boxes are not cells."""
    objects = _pdf_structure_objects(pdf)
    cells = [
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /(TD|TH)(?:/|>>)', body)]
    assert len(cells) == expected_count
    for _, body in cells:
        parent_reference = re.search(rb'/P (\d+ 0 R)', body).group(1)
        assert re.search(rb'/S /TR(?:/|>>)', objects[parent_reference])
    return objects, cells


def _structure_descendant_roles(objects, reference):
    body = objects[reference]
    children = re.search(rb'/K \[([^]]*)\]', body)
    if children is None:
        return
    for child_reference in re.findall(rb'\d+ 0 R', children.group(1)):
        child = objects[child_reference]
        if match := re.search(rb'/S /(\w+)(?:/|>>)', child):
            yield match.group(1)
        yield from _structure_descendant_roles(objects, child_reference)


def _structure_mcids(objects, reference):
    """Return the page marked-content IDs owned by a structure subtree."""
    children = re.search(rb'/K \[([^]]*)\]', objects[reference])
    if children is None:
        return []
    mcids = []
    for child_reference, mcid in re.findall(
            rb'(\d+ 0 R)|(\d+)', children.group(1)):
        if mcid:
            mcids.append(int(mcid))
        elif child_reference in objects:
            mcids.extend(_structure_mcids(objects, child_reference))
    return mcids


@pytest.mark.parametrize(
    ('cell_tag', 'attributes', 'content', 'content_role'), [
        ('td', '', '<p>paragraph</p>', b'P'),
        ('td', '', '<div>division</div>', b'Div'),
        ('td', '', '<span style="display:block">span</span>', b'Span'),
        ('th', ' scope="col"', '<p>paragraph</p>', b'P'),
        ('th', ' scope="col"', '<div>division</div>', b'Div'),
        ('th', ' scope="col"', '<span style="display:block">span</span>', b'Span'),
        ('td', '', 'before <p>first <span>second</span> third</p> after', b'P'),
    ])
@assert_no_logs
def test_pdf_tags_table_cell_block_children_are_not_nested(
        cell_tag, attributes, content, content_role):
    """Keep one source cell when a cell has native block descendants."""
    pdf = FakeHTML(string=f'''
      <html lang="en"><table><tr>
        <{cell_tag}{attributes}>{content}</{cell_tag}>
      </tr></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    objects, cells = _assert_table_cells_are_row_children(pdf, 1)
    assert len(re.findall(rb'/S /Table(?:/|>>)', pdf)) == 1
    assert re.search(fr'/S /{cell_tag.upper()}(?:/|>>)'.encode(), cells[0][1])
    if cell_tag == 'th':
        assert b'/Scope /Column' in cells[0][1]
    assert content_role in set(_structure_descendant_roles(objects, cells[0][0]))


@assert_no_logs
def test_pdf_tags_block_table_cells_keep_spans_and_headers():
    pdf = FakeHTML(string='''
      <html lang="en"><table>
        <thead><tr>
          <th id="first" scope="col"><div>first</div></th>
          <th id="second" scope="col"><span style="display:block">second</span></th>
          <th id="third" scope="col"><p>third</p></th>
        </tr></thead>
        <tbody>
          <tr>
            <td headers="first" rowspan="2"><div>rowspan</div></td>
            <td headers="second" colspan="2"><p>colspan</p></td>
          </tr>
          <tr>
            <td headers="second"><span style="display:block">second row</span></td>
            <td headers="third"><div>last</div></td>
          </tr>
        </tbody>
      </table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    objects, cells = _assert_table_cells_are_row_children(pdf, 7)
    table_reference, _ = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /Table(?:/|>>)', body))
    headers = [
        (reference, body) for reference, body in cells
        if re.search(rb'/S /TH(?:/|>>)', body)]
    data_cells = [
        body for _, body in cells if re.search(rb'/S /TD(?:/|>>)', body)]
    header_ids = [
        (reference, re.search(rb'/ID \(([^)]*)\)', header).group(1))
        for reference, header in headers]
    data_header_ids = [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', cell).group(1))
        for cell in data_cells]
    assert len(headers) == 3
    assert len(data_cells) == 4
    assert [
        role for role in _structure_descendant_roles(objects, table_reference)
        if role in (b'TH', b'TD')
    ] == [b'TH', b'TH', b'TH', b'TD', b'TD', b'TD', b'TD']
    assert all(b'/Scope /Column' in body for _, body in headers)
    assert b'/RowSpan 2' in pdf
    assert b'/ColSpan 2' in pdf
    assert data_header_ids == [
        [header_ids[0][1]], [header_ids[1][1]], [header_ids[1][1]],
        [header_ids[2][1]]]
    structure_root = next(
        body for body in objects.values() if b'/Type /StructTreeRoot' in body)
    id_tree_reference = re.search(
        rb'/IDTree (\d+ 0 R)', structure_root).group(1)
    id_tree = objects[id_tree_reference]
    assert all(
        b'(' + header_id + b') ' + header_reference in id_tree
        for header_reference, header_id in header_ids)


@assert_no_logs
def test_pdf_tags_fragmented_block_table_cells_keep_one_logical_table():
    rows = ''.join(
        f'<tr><td headers="header">before <p>row {index} '
        f'<span>inline</span></p> after</td></tr>'
        for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 28px; padding: 1px }}
        </style>
        <table>
          <thead><tr><th id="header" scope="col">
            <div>header <span>text</span></div>
          </th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    objects, cells = _assert_table_cells_are_row_children(pdf, 9)
    table_reference, _ = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /Table(?:/|>>)', body))
    headers = [
        (reference, body) for reference, body in cells
        if re.search(rb'/S /TH(?:/|>>)', body)]
    data_cells = [
        (reference, body) for reference, body in cells
        if re.search(rb'/S /TD(?:/|>>)', body)]
    header_id = re.search(rb'/ID \(([^)]*)\)', headers[0][1]).group(1)
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert len(re.findall(rb'/S /Table(?:/|>>)', pdf)) == 1
    assert len(re.findall(rb'/S /THead(?:/|>>)', pdf)) == 1
    assert len(re.findall(rb'/S /TBody(?:/|>>)', pdf)) == 1
    assert len(headers) == 1
    assert len(data_cells) == 8
    assert [
        role for role in _structure_descendant_roles(objects, table_reference)
        if role in (b'TH', b'TD')
    ] == [b'TH'] + [b'TD'] * 8
    assert b'Div' in set(_structure_descendant_roles(objects, headers[0][0]))
    assert all(
        b'P' in set(_structure_descendant_roles(objects, reference))
        for reference, _ in data_cells)
    assert all(
        b'/Headers [(' + header_id + b')]' in cell
        for _, cell in data_cells)
    assert pdf.count(b'/Artifact\nBMC') >= page_count - 1
    assert b'/ParentTree ' in pdf


@assert_no_logs
def test_pdf_tags_split_table_with_caption():
    # Regression test for #2761.
    FakeHTML(string='''
      <html lang="en" style="font: 2px/1 weasyprint">
        <style>@page { size: 3px }</style>
        <table><caption>caption</caption><tr><td>td</td></tr></table>
      </html>
    ''').write_pdf(pdf_tags=True)


@assert_no_logs
def test_pdf_tags_nested_lists_order():
    # Regression test for #2874.
    pdf = FakeHTML(string='''
      <html lang=fr><ul>
        <li>a</li>
        <li>
          ba
          <ul>
            <li>b1</li>
            <li>b2</li>
          </ul>
          bb
        </li>
        <li>c</li>
      </ul>
    ''').write_pdf(pdf_tags=True)
    list_children = re.findall(b'/S ?/L ?/K.*\\[(.*)\\]', pdf)
    for children in list_children:
        numbers = [int(number) for number in re.findall(b'[1-9][0-9]*', children)]
        assert sorted(numbers) == numbers


def _document_structure_roles(pdf):
    """Return every structure role below the document element, in tree order."""
    objects = _pdf_structure_objects(pdf)
    document = next(
        reference for reference, body in objects.items()
        if re.search(rb'/S /Document(?:/|>>)', body))
    return list(_structure_descendant_roles(objects, document))


def _semantic_structure_roles(pdf, roles):
    """Return the tagged order of the given roles only."""
    return [role for role in _document_structure_roles(pdf) if role in roles]


@pytest.mark.parametrize('flow_first', [True, False])
@assert_no_logs
def test_pdf_tags_flex_out_of_flow_child_keeps_source_order(flow_first):
    # Out-of-flow flex children used to be tagged before every flex item.
    heading = '<h1>title</h1>'
    badge = '<p style="position:absolute;top:0;right:0">badge</p>'
    children = heading + badge if flow_first else badge + heading
    pdf = FakeHTML(string=f'''
      <html lang="en"><body>
        <div style="display:flex;position:relative">{children}</div>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    expected = [b'H1', b'P'] if flow_first else [b'P', b'H1']
    assert _semantic_structure_roles(pdf, (b'H1', b'P')) == expected


@pytest.mark.parametrize('display', ['flex', 'grid'])
@assert_no_logs
def test_pdf_tags_visual_item_order_keeps_source_order(display):
    # The order property is a visual reordering: reading order is source order.
    pdf = FakeHTML(string=f'''
      <html lang="en"><body>
        <div style="display:{display}">
          <h1 style="order:2">title</h1>
          <p style="order:1">text</p>
        </div>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert _semantic_structure_roles(pdf, (b'H1', b'P')) == [b'H1', b'P']


@assert_no_logs
def test_pdf_tags_grid_placement_keeps_source_order():
    # Grid placement moves items between rows without moving reading order.
    pdf = FakeHTML(string='''
      <html lang="en"><body>
        <div style="display:grid;grid-template-rows:auto auto">
          <h1 style="grid-row:2">title</h1>
          <p style="grid-row:1">text</p>
        </div>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert _semantic_structure_roles(pdf, (b'H1', b'P')) == [b'H1', b'P']


@assert_no_logs
def test_pdf_tags_broken_out_of_flow_keeps_source_order():
    # Content resumed out of flow used to be tagged in front of the page it
    # resumes on. It cannot be nested back inside its source parent, but it
    # keeps its source position among the boxes it is a sibling of.
    pdf = FakeHTML(string='''
      <html lang="en"><head><style>
        @page { size: 60px 40px; margin: 0 }
        body, blockquote { margin: 0 }
        h1, p, div { font-size: 8px; line-height: 10px; margin: 0 }
        blockquote { position: absolute; top: 0; left: 30px; width: 25px }
      </style></head><body>
        <h1>t</h1>
        <blockquote><p>a1</p><p>a2</p><p>a3</p><p>a4</p><p>a5</p></blockquote>
        <div>b1</div><div>b2</div><div>b3</div>
        <div>b4</div><div>b5</div><div>b6</div>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert _semantic_structure_roles(pdf, (b'H1', b'BlockQuote', b'Div')) == [
        b'H1', b'BlockQuote', b'Div', b'Div', b'Div',
        b'Div', b'Div', b'Div', b'BlockQuote']


def _marked_content_order(pdf):
    """Return the tag names of the page's marked content, in painting order."""
    return re.findall(rb'/(\w+)\s*<</MCID \d+>>\s*BDC', pdf)


@assert_no_logs
@pytest.mark.parametrize('display', ['block', 'inline'])
def test_pdf_image_marked_content_follows_source_order(display):
    # The UA stylesheet clips every image, which used to make each one its own
    # stacking context. Painting one last put its marked content after all the
    # text on the page, and that is the order reading-order tools display.
    # The test UA stylesheet does not clip, so the fixture asks for it.
    pdf = _tagged_image_pdf(
        '<p>before</p>'
        '<img src="{image_url}" alt="image"'
        f' style="display:{display};overflow:hidden">'
        '<p>after</p>')
    assert _marked_content_order(pdf) == [b'Span', b'Figure', b'Span']


@assert_no_logs
def test_pdf_image_keeps_its_own_stacking_context_when_transformed():
    # Only the clip stopped making images stacking contexts. A transformed
    # image still is one, so CSS still paints it above its in-flow siblings.
    pdf = _tagged_image_pdf(
        '<p>before</p>'
        '<img src="{image_url}" alt="image"'
        ' style="overflow:hidden;transform:rotate(5deg)">'
        '<p>after</p>')
    assert _marked_content_order(pdf) == [b'Span', b'Span', b'Figure']


def _tagged_image_pdf(content):
    """Render one image-tagging fixture with a visible raster image."""
    image_url = path2url(resource_path('pattern.png'))
    return FakeHTML(string=f'''
      <html lang="en"><body>
        {content.format(image_url=image_url)}
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)


def _assert_tagged_transparency_group_has_parent_tree_entry(pdf):
    """Ensure tagged Form content has a ParentTree entry and an MCR link."""
    objects = _pdf_structure_objects(pdf)
    group_reference, group = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/Type /XObject.*?/Subtype /Form', body, re.S) and
        b'/S /Transparency' in body and b'/MCID' in body)
    struct_parents = re.search(rb'/StructParents (\d+)', group)
    assert struct_parents

    structure_root = next(
        body for body in objects.values() if b'/Type /StructTreeRoot' in body)
    parent_tree_reference = re.search(
        rb'/ParentTree (\d+ 0 R)', structure_root).group(1)
    parent_tree = objects[parent_tree_reference]
    entry = re.search(
        rb'(?<!\d)' + struct_parents.group(1) + rb' \[([^]]*)\]',
        parent_tree, re.S)
    assert entry

    figure_reference, figure = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /Figure(?:/|>>)', body))
    assert figure_reference in re.findall(rb'\d+ 0 R', entry.group(1))
    assert re.search(
        rb'/K \[<</Type /MCR/MCID \d+/Pg \d+ 0 R/Stm ' +
        re.escape(group_reference) + rb'>>\]', figure)


def _assert_caption_owned_by_figure(pdf):
    objects = {
        reference: body
        for reference, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}
    figure = next(
        body for body in objects.values()
        if re.search(rb'/S /Figure(?:/|>>)', body))
    caption_reference = next(
        reference for reference, body in objects.items()
        if re.search(rb'/S /Caption(?:/|>>)', body))
    assert re.search(rb'\b' + caption_reference + rb' 0 R\b', figure)


@assert_no_logs
def test_pdf_tags_meaningful_image_has_alt_and_parent_tree():
    pdf = _tagged_image_pdf('''
      <img src="{image_url}" alt="Arizona state seal">
    ''')

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Arizona state seal)') == 1
    assert b'/MCID' in pdf
    assert b'/ParentTree ' in pdf


@assert_no_logs
def test_pdf_tags_one_pixel_state_carrier_is_meaningful():
    transparent_pixel = (
        'data:image/gif;base64,'
        'R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')
    pdf = FakeHTML(string=f'''
      <html lang="en"><body>
        <p>Before <img src="{transparent_pixel}" alt="Checked checkbox:"
        width="1" height="1"> after</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Checked checkbox:)') == 1
    assert b'/MCID' in pdf


@assert_no_logs
def test_pdf_tags_absolute_state_image_in_css_table_keeps_surrounding_content():
    image_url = path2url(resource_path('pattern.png'))
    pdf = FakeHTML(string=f'''
      <html lang="en"><head><style>
        .control-line {{
          display: table;
          width: 100%;
          table-layout: auto;
          border-collapse: collapse;
        }}
        .control-slot {{ display: table-cell; width: 13pt; vertical-align: middle }}
        .label-slot {{
          display: table-cell;
          padding-right: 3pt;
          white-space: nowrap;
        }}
        .value-slot {{
          display: table-cell;
          width: 100%;
          vertical-align: middle;
          border-bottom: .75pt solid #000;
        }}
        .checkbox-control {{
          position: relative;
          display: inline-block;
          width: 11pt;
          height: 11pt;
        }}
        .semantic-state {{
          position: absolute;
          width: 1pt;
          height: 1pt;
          opacity: 0;
        }}
      </style></head><body>
        <p>Before the control line.</p>
        <span class="control-line">
          <span class="control-slot">
            <span class="checkbox-control">
              <span class="checkbox-box">✓</span>
              <img class="semantic-state" src="{image_url}"
                   alt="Checked checkbox:">
            </span>
          </span>
          <span class="label-slot">County Office:</span>
          <span class="value-slot">Assessor</span>
        </span>
        <p>After the control line.</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Checked checkbox:)') == 1
    assert pdf.count(b'/MCID') >= 5
    assert b'/ParentTree ' in pdf
    _assert_tagged_transparency_group_has_parent_tree_entry(pdf)


@assert_no_logs
def test_pdf_tags_decorative_image_is_an_artifact_but_is_painted():
    pdf = _tagged_image_pdf('''
      <img src="{image_url}" alt="">
    ''')

    assert not re.search(rb'/S /Figure(?:/|>>)', pdf)
    assert re.search(rb'/Artifact\s+BMC', pdf)
    assert b'/XObject' in pdf


def test_pdf_tags_missing_image_alt_keeps_missing_description_evidence():
    with capture_logs() as logs:
        pdf = _tagged_image_pdf('''
          <img src="{image_url}">
        ''')

    assert logs == [
        f'ERROR: Image "{path2url(resource_path("pattern.png"))}" '
        'has no required alt description']
    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert b'/Alt ' not in pdf
    assert b'/MCID' in pdf


@pytest.mark.parametrize('attributes', [
    'role="presentation"',
    'role="none"',
    'role="none presentation"',
    'role="bogus presentation"',
    'aria-hidden="true"',
])
@assert_no_logs
def test_pdf_tags_presentational_images_are_artifacts(attributes):
    pdf = _tagged_image_pdf(f'''
      <img src="{{image_url}}" alt="presentational image" {attributes}>
    ''')

    assert not re.search(rb'/S /Figure(?:/|>>)', pdf)
    assert re.search(rb'/Artifact\s+BMC', pdf)
    assert b'/XObject' in pdf


@pytest.mark.parametrize('role', ['button', 'marquee', 'suggestion'])
@assert_no_logs
def test_pdf_tags_presentational_role_fallback_keeps_supported_roles_semantic(
        role):
    pdf = _tagged_image_pdf(f'''
      <img src="{{image_url}}" alt="{role} image" role="{role} presentation">
    ''')

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(f'/Alt ({role} image)'.encode()) == 1


@assert_no_logs
def test_pdf_tags_figure_caption_has_one_figure_and_one_caption():
    pdf = _tagged_image_pdf('''
      <figure>
        <img src="{image_url}" alt="Quarterly spending chart">
        <figcaption>Quarterly spending</figcaption>
      </figure>
    ''')

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert len(re.findall(rb'/S /Caption(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Quarterly spending chart)') == 1
    _assert_caption_owned_by_figure(pdf)


@assert_no_logs
def test_pdf_tags_figure_caption_is_owned_before_the_image():
    pdf = _tagged_image_pdf('''
      <figure>
        <figcaption>Quarterly spending</figcaption>
        <img src="{image_url}" alt="Quarterly spending chart">
      </figure>
    ''')

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert len(re.findall(rb'/S /Caption(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Quarterly spending chart)') == 1
    _assert_caption_owned_by_figure(pdf)


@assert_no_logs
def test_pdf_tags_inline_svg_uses_title_without_duplicate_description():
    pdf = FakeHTML(string='''
      <html lang="en"><body>
        <svg width="10" height="10" xmlns="http://www.w3.org/2000/svg">
          <title>Quarterly spending chart</title>
          <desc>Bars compare each quarter.</desc>
          <rect width="10" height="10" fill="blue"/>
        </svg>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Quarterly spending chart)') == 1
    assert b'/Alt (Bars compare each quarter.)' not in pdf


@assert_no_logs
def test_pdf_tags_inline_svg_uses_desc_when_title_is_missing():
    pdf = FakeHTML(string='''
      <html lang="en"><body>
        <svg width="10" height="10" xmlns="http://www.w3.org/2000/svg">
          <desc>Quarterly spending chart</desc>
          <rect width="10" height="10" fill="blue"/>
        </svg>
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)

    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (Quarterly spending chart)') == 1


def test_pdf_tags_table_headers():
    pdf = FakeHTML(string='''
      <html lang="fr">
        <table>
          <thead>
            <th></th><th>1</th><th>2</th><th>3</th>
          </thead>
          <tr>
            <th scope="row">1</th><td>1-1</td><td>1-2</td>
          </tr>
          <tr>
            <th scope="row">2</th><td>2-1</td><td rowspan="2">2/3-2</td><td>2-3</td>
          </tr>
          <tr>
            <th scope="row">3</th><td>3-1</td><td>3-3</td>
          </tr>
          <tr>
            <th scope="row">4</th><td colspan="3">4-1/2/3</td>
          </tr>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert pdf.count(b'/RowSpan 2') == 1
    assert pdf.count(b'/ColSpan 3') == 1
    id = re.findall(b'(.+) 0 obj\n.*/S /Table', pdf)[0].decode()
    assert f'[({id}-1-0) ({id}-0-1)]'.encode() in pdf
    assert f'[({id}-2-0) ({id}-3-0) ({id}-0-2)]'.encode() in pdf
    assert f'[({id}-4-0) ({id}-0-1) ({id}-0-2) ({id}-0-3)]'.encode() in pdf


def test_pdf_tags_explicit_table_headers_invalid_tokens():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tr>
        <th id="row" scope="row">Row</th>
        <th id="column" scope="col">Column<span id="not-a-header"></span></th>
        <td headers="column unknown not-a-header row column">partial</td>
        <td headers="">empty</td>
      </tr></table>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    table_id = re.findall(b'(.+) 0 obj\n.*/S /Table', pdf)[0].decode()
    assert f'/Headers [({table_id}-0-1) ({table_id}-0-0)]'.encode() in pdf
    assert pdf.count(b'/Headers []') == 1


def test_pdf_tags_explicit_table_headers_include_empty_headers():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tr>
        <th id="blank" scope="col"></th><td headers="blank">data</td>
      </tr></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header = next(
        body for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    header_id = re.search(rb'/ID \(([^)]*)\)', header).group(1)
    table_cell = next(
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body))
    assert b'/Headers [(' + header_id + b')]' in table_cell


def test_pdf_tags_table_headers_are_registered_in_id_tree():
    pdf = FakeHTML(string='''
      <html lang="en"><table>
        <thead><tr><th id="header" scope="col">header</th></tr></thead>
        <tbody><tr><td headers="header">data</td></tr></tbody>
      </table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = {
        b'%s 0 R' % reference: body
        for reference, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}
    header_reference, header = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /TH(?:/|>>)', body))
    header_id = re.search(rb'/ID \(([^)]*)\)', header).group(1)
    structure_root = next(
        body for body in objects.values() if b'/Type /StructTreeRoot' in body)
    id_tree_reference = re.search(rb'/IDTree (\d+ 0 R)', structure_root).group(1)
    id_tree = objects[id_tree_reference]
    assert b'(' + header_id + b') ' + header_reference in id_tree


@pytest.mark.parametrize(('scope', 'rows'), [
    ('col', '<tr><th scope="col"></th></tr><tr><td>data</td></tr>'),
    ('row', '<tr><th scope="row"></th><td>data</td></tr>'),
])
def test_pdf_tags_empty_scoped_table_headers_are_associated(scope, rows):
    pdf = FakeHTML(string=f'''
      <html lang="en"><table><tbody>{rows}</tbody></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cell = next(
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body))
    assert b'/Headers [(' + header_id + b')]' in table_cell


def test_pdf_tags_explicit_table_headers_exclude_the_principal_cell():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tr>
        <th id="header" headers="header">header</th>
      </tr></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    header = next(
        body for body in re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
        if re.search(rb'/S /TH(?:/|>>)', body))
    assert b'/Headers []' in header


@pytest.mark.parametrize(('table', 'cell_count'), [
    ('''
      <table><tr><th scope="ROW">row</th><td>row data</td></tr></table>
    ''', 1),
    ('''
      <table><tbody>
        <tr><th scope="rowgroup" rowspan="2">row group</th><td>1</td></tr>
        <tr><td>2</td></tr>
      </tbody></table>
    ''', 2),
    ('''
      <table>
        <colgroup span="2"></colgroup>
        <tr><th scope="colgroup" colspan="2">column group</th></tr>
        <tr><td>3</td><td>4</td></tr>
      </table>
    ''', 2),
])
def test_pdf_tags_table_header_scope_associations(table, cell_count):
    pdf = FakeHTML(string=f'''
      <html lang="en">{table}</html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_ids = [
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(header_ids) == 1
    assert len(table_cells) == cell_count
    expected_headers = [header_ids[0]] * cell_count
    actual_headers = [
        match.group(1) if (
            match := re.search(rb'/Headers \[\(([^)]*)\)\]', body)) else None
        for body in table_cells]
    assert actual_headers == expected_headers


def test_pdf_tags_row_scope_associates_rowspans():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tbody>
        <tr><th id="row" scope="row" rowspan="2">row</th><td>first</td></tr>
        <tr><td>second</td></tr>
      </tbody></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    row_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in table_cells] == [[row_id], [row_id]]


def test_pdf_tags_row_scope_only_associates_cells_to_its_right():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tbody>
        <tr><td>before</td><th id="row" scope="row">row</th><td>after</td></tr>
      </tbody></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    row_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in table_cells] == [[], [row_id]]


def test_pdf_tags_rowgroup_scope_only_associates_remaining_cells():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tbody>
        <tr><td>before</td><th id="group" scope="rowgroup">group</th><td>after</td></tr>
        <tr><td>left</td><td>middle</td><td>right</td></tr>
      </tbody></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    group_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in table_cells] == [[], [group_id], [], [group_id], [group_id]]


def test_pdf_tags_colgroup_scope_uses_the_column_group():
    pdf = FakeHTML(string='''
      <html lang="en"><table>
        <colgroup span="3"></colgroup>
        <tbody>
          <tr>
            <th id="group" scope="colgroup">group</th>
            <th id="second" scope="col">second</th>
            <th id="third" scope="col">third</th>
          </tr>
          <tr><td>one</td><td>two</td><td>three</td></tr>
        </tbody>
      </table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    headers = [
        (re.search(rb'/ID \(([^)]*)\)', body).group(1), body)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    group_id = next(header_id for header_id, body in headers
                    if b'/Scope' not in body)
    second_id, third_id = [
        header_id for header_id, body in headers
        if b'/Scope /Column' in body]
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert [
        set(re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1)))
        for body in table_cells] == [
            {group_id}, {group_id, second_id}, {group_id, third_id}]


def test_pdf_tags_colgroup_scope_associates_spanning_cells_in_each_group():
    pdf = FakeHTML(string='''
      <html lang="en"><table>
        <colgroup span="1"></colgroup><colgroup span="1"></colgroup>
        <tbody>
          <tr>
            <th scope="colgroup">first group</th>
            <th scope="colgroup">second group</th>
          </tr>
          <tr><td colspan="2">spanning cell</td></tr>
        </tbody>
      </table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_ids = {
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body)}
    table_cell = next(
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body))
    assert set(re.findall(rb'\(([^)]*)\)', re.search(
        rb'/Headers \[([^]]*)\]', table_cell).group(1))) == header_ids


def test_pdf_tags_table_headers_follow_html_scope_order():
    pdf = FakeHTML(string='''
      <html lang="en"><table>
        <colgroup span="3"></colgroup>
        <tbody>
          <tr>
            <th scope="rowgroup">row group</th>
            <th scope="colgroup" colspan="2">column group</th>
          </tr>
          <tr>
            <th scope="col">first column</th>
            <th scope="col">second column</th>
            <th scope="col">third column</th>
          </tr>
          <tr>
            <th scope="row">row</th><td>target</td><td>other</td>
          </tr>
        </tbody>
      </table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    headers = [
        (re.search(rb'/ID \(([^)]*)\)', body).group(1), body)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    row_id = next(header_id for header_id, body in headers
                  if b'/Scope /Row' in body)
    column_ids = [header_id for header_id, body in headers
                  if b'/Scope /Column' in body]
    rowgroup_id, colgroup_id = [
        header_id for header_id, body in headers if b'/Scope' not in body]
    table_cells = [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert [row_id, column_ids[1], rowgroup_id, colgroup_id] in table_cells


def test_pdf_tags_column_scope_only_associates_subsequent_rows():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tbody>
        <tr><td>before</td><td>before second</td></tr>
        <tr><th id="header" scope="col" rowspan="2">header</th><td>middle</td></tr>
        <tr><td>middle second</td></tr>
        <tr><td>after</td><td>after second</td></tr>
      </tbody></table></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    headers = [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in table_cells]
    assert headers[0] == []
    assert headers[-2] == [header_id]


def test_pdf_tags_explicit_table_headers_across_pages():
    rows = ''.join(
        f'<tr><td headers="header">row {index}</td></tr>'
        for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table><tbody>
          <tr><th id="header" scope="col">header</th></tr>
          {rows}
        </tbody></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(table_cells) == 8
    assert all(
        b'/Headers [(' + header_id + b')]' in body
        for body in table_cells)


def test_pdf_tags_explicit_table_headers_across_pages_forward_reference():
    rows = ''.join(
        f'<tr><td headers="header">row {index}</td></tr>'
        for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table><tbody>
          {rows}
          <tr><th id="header" scope="col">header</th></tr>
        </tbody></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(table_cells) == 8
    assert all(
        b'/Headers [(' + header_id + b')]' in body
        for body in table_cells)


def test_pdf_tags_inferred_table_headers_across_pages():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table><tbody>
          <tr><th scope="col">header</th></tr>
          {rows}
        </tbody></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(table_cells) == 8
    assert all(
        b'/Headers [(' + header_id + b')]' in body
        for body in table_cells)


def test_pdf_tags_fragmented_row_headers_use_the_contentful_header():
    lines = '<br>'.join(['text'] * 20)
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 100px; margin: 5px }}
          td, th {{ line-height: 20px }}
        </style>
        <table><tbody>
          <tr><th scope="row">row</th><td>{lines}</td></tr>
        </tbody></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    headers = [
        (re.search(rb'/ID \(([^)]*)\)', body).group(1), body)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body) and
        re.search(rb'/ID \(([^)]*)\)', body)]
    content_header_ids = [
        header_id for header_id, body in headers if b'/K []' not in body]
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(table_cells) > 1
    assert len(content_header_ids) == 1
    assert [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in table_cells] == [[content_header_ids[0]]] * len(table_cells)


def test_pdf_tags_fragmented_headers_do_not_reference_themselves():
    lines = '<br>'.join(['text'] * 20)
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 100px; margin: 5px }}
          td, th {{ line-height: 20px }}
        </style>
        <table><tbody>
          <tr>
            <th id="row" headers="row" scope="row">row</th>
            <td headers="row">{lines}</td>
          </tr>
        </tbody></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    headers = [
        body for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    assert len(headers) > 1
    assert all(b'/Headers []' in body for body in headers)


def test_pdf_tags_footer_headers_follow_body_rows_across_pages():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <tbody>{rows}</tbody>
          <tfoot><tr><th scope="col">footer header</th></tr></tfoot>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(table_cells) == 8
    assert all(b'/Headers []' in body for body in table_cells)


def test_pdf_tags_rowgroup_headers_across_pages():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table><tbody>
          <tr><th scope="rowgroup">group</th></tr>
          {rows}
        </tbody></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(table_cells) == 8
    assert all(
        b'/Headers [(' + header_id + b')]' in body
        for body in table_cells)


def test_pdf_tags_colgroup_headers_across_pages():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <colgroup span="1"></colgroup>
          <tbody>
            <tr><th scope="colgroup">group</th></tr>
            {rows}
          </tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_id = next(
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(table_cells) == 8
    assert all(
        b'/Headers [(' + header_id + b')]' in body
        for body in table_cells)


def test_pdf_tags_repeated_table_headers_are_artifacts():
    rows = ''.join(
        f'<tr><td headers="header">row {index}</td></tr>'
        for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
              @page {{ size: 200px 120px; margin: 5px }}
              td, th {{ height: 35px }}
            </style>
            <table>
              <thead><tr><th id="header" scope="col">
                header<a href="https://example.test">linked header</a>
                <span style="position: absolute">absolute header</span>
              </th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header_ids = [
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert len(header_ids) == 1
    assert all(
        re.search(rb'/Headers \[\(([^)]*)\)\]', body).group(1) == header_ids[0]
        for body in table_cells)
    assert pdf.count(b'/S /Link') == 1
    assert pdf.count(b'/Subtype /Link') == page_count
    assert pdf.count(b'/Type /OBJR') == page_count
    assert pdf.count(b'/StructParent ') == page_count
    assert b'/ParentTree ' in pdf


@assert_no_logs
@pytest.mark.parametrize('content', [
    'first line<br>second line',
    '<img src="pattern.png" alt="Pattern" style="width: 20px; height: 20px">',
])
def test_pdf_tags_annotations_inside_link_belong_to_link(content):
    # Boxes inside a link (line breaks, images) get their own link annotations.
    # PDF/UA requires every link annotation to be referenced from a Link element.
    pdf = FakeHTML(
        string=f'<html lang="en"><p><a href="https://example.test">{content}</a></p>',
        base_url=resource_path('<inline HTML>'),
    ).write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = dict(re.findall(rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S))
    (parent_tree,) = [
        body for body in objects.values() if b'/Nums [' in body]
    nums = re.search(rb'/Nums \[(.*)\]', parent_tree, re.S).group(1)
    tokens = re.findall(rb'\[[^\]]*\]|\d+ 0 R|\d+', nums)
    owners = dict(zip(tokens[0::2], tokens[1::2]))
    annotations = [
        body for body in objects.values() if b'/Subtype /Link' in body]
    assert len(annotations) > 1
    for annotation in annotations:
        struct_parent = re.search(rb'/StructParent (\d+)', annotation).group(1)
        owner = objects[owners[struct_parent].split()[0]]
        assert b'/S /Link' in owner


def test_pdf_tags_repeated_document_writes_keep_link_owners():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    document = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr><th><a href="https://example.test">header</a></th></tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').render()
    page_count = len(document.pages)

    for _ in range(25):
        pdf = document.write_pdf(pdf_tags=True, uncompressed_pdf=True)
        assert pdf.count(b'/S /Link') == 1
        assert pdf.count(b'/Subtype /Link') == page_count
        assert pdf.count(b'/Type /OBJR') == page_count
        assert pdf.count(b'/StructParent ') == page_count
        del pdf
        gc.collect()


def test_pdf_tags_delayed_thead_is_semantic_before_repetitions():
    rows = '''
      <tr><td class="tall" headers="header">first row</td></tr>
      <tr><td class="short" headers="header">second row</td></tr>
      <tr><td class="short" headers="header">third row</td></tr>
    '''
    pdf = HTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 180px; margin: 5px }}
          td, th {{ border: 0; padding: 0 }}
          td.tall {{ height: 140px }}
          td.short {{ height: 20px }}
        </style>
        <table>
          <thead><tr><th id="header" scope="col">
            <a href="https://example.test">header</a>
          </th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    header = next(
        body for body in objects if re.search(rb'/S /TH(?:/|>>)', body))
    header_id = re.search(rb'/ID \(([^)]*)\)', header).group(1)
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len([
        body for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]) == 1
    assert all(b'/Headers [(' + header_id + b')]' in body
               for body in table_cells)
    assert pdf.count(b'/S /Link') == 1
    object_bodies = {
        b'%s 0 R' % reference: body
        for reference, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}
    table = next(
        body for body in objects if re.search(rb'/S /Table(?:/|>>)', body))
    table_children = re.findall(
        rb'\d+ 0 R', re.search(rb'/K \[([^]]*)\]', table).group(1))
    table_group_roles = [
        re.search(rb'/S /(THead|TBody)', object_bodies[reference]).group(1)
        for reference in table_children
        if re.search(rb'/S /(THead|TBody)', object_bodies[reference])]
    assert table_group_roles == [b'THead', b'TBody']


def test_pdf_tags_repeated_table_header_widgets_have_structural_owners():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr><th><input name="header-input"></th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, pdf_forms=True, uncompressed_pdf=True)
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert pdf.count(b'/S /Form') == page_count
    assert pdf.count(b'/Subtype /Widget') == page_count
    assert pdf.count(b'/Type /OBJR') == page_count
    assert pdf.count(b'/StructParent ') == page_count
    assert b'/ParentTree ' in pdf


def test_pdf_tags_repeated_table_header_image_links_have_structural_owners():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr><th><a href="https://example.test"><img
            alt="icon"
            src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
          ></a></th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert len(re.findall(rb'/S /TH(?:/|>>)', pdf)) == 1
    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/S /Link') == 1
    assert pdf.count(b'/Subtype /Link') == 2 * page_count
    assert pdf.count(b'/Type /OBJR') == 2 * page_count
    assert pdf.count(b'/StructParent ') == 2 * page_count
    assert b'/ParentTree ' in pdf


@pytest.mark.parametrize(
    'positioning', ['float: left', 'position: absolute', 'position: fixed'])
def test_pdf_tags_repeated_table_header_out_of_flow_images_are_canonical(
        positioning):
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr><th><a href="https://example.test"><img
            alt="header icon" style="{positioning}"
            src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
          ></a></th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (header icon)') == 1
    assert pdf.count(b'/S /Link') == 1
    assert pdf.count(b'/Subtype /Link') == 2 * page_count
    assert pdf.count(b'/Type /OBJR') == 2 * page_count
    link_annotations = [
        body for body in re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
        if b'/Subtype /Link' in body]
    assert all(b'/StructParent ' in annotation for annotation in link_annotations)


def test_pdf_tags_repeated_table_header_fixed_text_is_artifact():
    rows = ''.join('<tr><td></td></tr>' for _ in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr><th><span style="position: fixed">header</span></th></tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    # The inline element and its text are the two canonical Span elements.
    assert len(re.findall(rb'/S /Span(?:/|>>)', pdf)) == 2


@pytest.mark.parametrize('positioning', ['absolute', 'fixed'])
def test_pdf_tags_repeated_table_header_fixed_container_image_is_artifact(
        positioning):
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr><th><div style="position: fixed"><img
            alt="fixed header icon" style="position: {positioning}"
            src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
          ></div></th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert len(re.findall(rb'/S /Figure(?:/|>>)', pdf)) == 1
    assert pdf.count(b'/Alt (fixed header icon)') == 1
    assert pdf.count(b'/Artifact\nBMC') >= page_count - 1


def test_pdf_tags_fragmented_table_has_one_logical_structure():
    rows = ''.join(
        f'<tr><td headers="first">first {index}</td>'
        f'<td headers="second">second {index}</td></tr>'
        for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
        </style>
        <table>
          <thead><tr>
            <th id="first" scope="col">first</th>
            <th id="second" scope="col">second</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    tables = [
        body for body in objects if re.search(rb'/S /Table(?:/|>>)', body)]
    headers = [
        body for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len(tables) == 1
    assert len(headers) == 2
    assert len([
        body for body in objects if re.search(rb'/S /THead(?:/|>>)', body)]) == 1
    assert len([
        body for body in objects if re.search(rb'/S /TBody(?:/|>>)', body)]) == 1
    header_ids = {
        re.search(rb'/ID \(([^)]*)\)', body).group(1) for body in headers}
    table_cells = [
        body for body in objects
        if re.search(rb'/S /TD(?:/|>>)', body)]
    referenced_ids = {
        re.search(rb'/Headers \[\(([^)]*)\)\]', body).group(1)
        for body in table_cells}
    assert referenced_ids == set(header_ids)

    structure_root = next(
        body for body in objects if b'/Type /StructTreeRoot' in body)
    assert b'/IDTree ' in structure_root
    id_tree = next(
        body for body in objects
        if b'/Names' in body and all(
            b'(' + header_id + b')' in body for header_id in header_ids))
    assert all(id_tree.count(b'(' + header_id + b')') == 1
               for header_id in header_ids)


def test_pdf_tags_fragmented_table_bottom_caption_is_canonical():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
          caption {{ caption-side: bottom }}
        </style>
        <table>
          <caption>table caption</caption>
          <thead><tr><th scope="col">header</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = {
        b'%s 0 R' % reference: body
        for reference, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}
    table_reference, table = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /Table(?:/|>>)', body))
    caption = next(
        body for body in objects.values() if re.search(rb'/S /Caption(?:/|>>)', body))
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len([
        body for body in objects.values() if re.search(rb'/S /Table(?:/|>>)', body)
    ]) == 1
    assert b'/P ' + table_reference in caption


def test_pdf_tags_fragmented_table_top_caption_is_canonical():
    caption_lines = '<br>'.join(['table caption'] * 20)
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          td, th {{ height: 35px }}
          caption {{ caption-side: top; line-height: 20px }}
        </style>
        <table>
          <caption>{caption_lines}</caption>
          <thead><tr><th scope="col">header</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = {
        b'%s 0 R' % reference: body
        for reference, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)}
    table_reference, _ = next(
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /Table(?:/|>>)', body))
    captions = [
        body for body in objects.values() if re.search(rb'/S /Caption(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len([
        body for body in objects.values() if re.search(rb'/S /Table(?:/|>>)', body)
    ]) == 1
    assert len(captions) == 1
    assert b'/P ' + table_reference in captions[0]


def test_pdf_tags_fragmented_table_artifacts_repeated_headers():
    rows = ''.join(f'<tr><td>row {index}</td></tr>' for index in range(8))
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 120px; margin: 5px }}
          table {{ border-collapse: collapse }}
          td, th {{ border: 0; height: 35px; padding: 0 }}
        </style>
        <table>
          <thead><tr><th scope="col">header</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    structure_root = next(
        body for body in objects if b'/Type /StructTreeRoot' in body)
    page_count = len(re.findall(rb'/Type /Page\b', pdf))
    assert page_count > 1
    assert b'/ParentTree ' in structure_root
    assert pdf.count(b'/StructParents ') == page_count
    assert pdf.count(b'/Artifact\nBMC') >= page_count - 1
    assert b'/MCID ' in pdf


def test_pdf_tags_fragmented_table_reuses_body_header_structure():
    lines = '<br>'.join(['text'] * 20)
    pdf = FakeHTML(string=f'''
      <html lang="en">
        <style>
          @page {{ size: 200px 100px; margin: 5px }}
          td, th {{ line-height: 20px }}
        </style>
        <table>
          <thead><tr><th id="column" scope="col">column</th></tr></thead>
          <tbody><tr>
            <th id="row" scope="row">row</th>
            <td headers="column row">{lines}</td>
          </tr></tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    headers = [
        body for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    header_ids = {
        re.search(rb'/ID \(([^)]*)\)', body).group(1) for body in headers}
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert len([
        body for body in objects if re.search(rb'/S /Table(?:/|>>)', body)]) == 1
    assert len(headers) == 2
    assert len(table_cells) == 1
    assert re.findall(
        rb'\(([^)]*)\)', re.search(rb'/Headers \[([^]]*)\]', table_cells[0]).group(1)
    ) == sorted(header_ids)


def test_pdf_tags_fragmented_table_persists_rowspan_row_headers():
    pdf = FakeHTML(string='''
      <html lang="en">
        <style>
          @page { size: 200px 120px; margin: 5px }
          td, th { height: 35px }
        </style>
        <table>
          <thead><tr>
            <th scope="col">first column</th>
            <th scope="col">second column</th>
          </tr></thead>
          <tbody>
            <tr><th scope="row" rowspan="3">row header</th><td>one</td></tr>
            <tr><td>two</td></tr>
            <tr><td>three</td></tr>
            <tr><td>after</td><td>after second</td></tr>
          </tbody>
        </table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    headers = [
        (re.search(rb'/ID \(([^)]*)\)', body).group(1), body)
        for body in objects if re.search(rb'/S /TH(?:/|>>)', body)]
    row_id = next(header_id for header_id, body in headers
                  if b'/Scope /Row' in body)
    column_ids = [header_id for header_id, body in headers
                  if b'/Scope /Column' in body]
    table_cells = [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    assert table_cells == [
        [row_id, column_ids[1]],
        [row_id, column_ids[1]],
        [row_id, column_ids[1]],
        [column_ids[0]],
        [column_ids[1]],
    ]


def test_pdf_tags_explicit_table_headers_stay_in_table():
    pdf = FakeHTML(string='''
      <html lang="en">
        <table><tr><th id="header">first</th><td headers="header">1</td></tr></table>
        <table><tr><td headers="header">2</td></tr></table>
      </html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    objects = re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
    table_cells = [
        body for body in objects if re.search(rb'/S /TD(?:/|>>)', body)]
    assert len(table_cells) == 2
    assert b'/Headers []' not in table_cells[0]
    assert b'/Headers []' in table_cells[1]


def test_pdf_tags_table_header_scopes():
    pdf = FakeHTML(string='''
      <html lang="en"><table><tr>
        <th scope="row">row</th>
        <th scope="rowgroup">rowgroup</th>
        <th scope="col">column</th>
        <th scope="colgroup">colgroup</th>
      </tr></table>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    table_id = re.findall(b'(.+) 0 obj\n.*/S /Table', pdf)[0].decode()
    header_objects = {
        re.search(rb'/ID \(([^)]*)\)', body).group(1): body
        for body in re.findall(rb'\d+ 0 obj\n(.*?)\nendobj', pdf, re.S)
        if re.search(rb'/S /TH(?:/|>>)', body)
    }
    assert b'/Scope /Row' in header_objects[f'{table_id}-0-0'.encode()]
    assert b'/Scope' not in header_objects[f'{table_id}-0-1'.encode()]
    assert b'/Scope /Column' in header_objects[f'{table_id}-0-2'.encode()]
    assert b'/Scope' not in header_objects[f'{table_id}-0-3'.encode()]
    assert b'/Scope /RowGroup' not in pdf
    assert b'/Scope /ColumnGroup' not in pdf


def test_pdf_tags_grouped_table_with_block_header_content():
    pdf = FakeHTML(filename=resource_path(
        'paperlyft_campaign_transactions.html')).write_pdf(pdf_tags=True)

    assert pdf.count(b'/RowSpan 2') == 4
    assert pdf.count(b'/ColSpan 2') == 1
    assert pdf.count(b'/ColSpan 3') == 1
    assert pdf.count(b'/ColSpan 4') == 1

    objects = {
        int(number): body for number, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)
    }
    header_ids = []
    for body in objects.values():
        if not re.search(rb'/S /TH(?:/|>>)', body):
            continue
        parent_number = int(re.search(rb'/P (\d+) 0 R', body).group(1))
        assert re.search(rb'/S /TR(?:/|>>)', objects[parent_number])
        header_ids.append(re.search(rb'/ID \(([^)]*)\)', body).group(1))

    assert len(header_ids) == 12
    # Each generated header ID is also registered once in the PDF IDTree.
    assert [pdf.count(b'(' + id + b')') - 1 for id in header_ids] == [
        1, 13, 11, 6, 5, 5, 5, 6, 6, 13, 13, 4]


@pytest.mark.parametrize(('filename', 'table_count'), [
    ('paperlyft_reporting_period_summary.html', 2),
    ('paperlyft_income_expense_ledger.html', 1),
    ('paperlyft_real_property_disclosure.html', 1),
    ('paperlyft_campaign_transactions.html', 1),
    ('paperlyft_schedule_b1_disbursements.html', 1),
])
def test_pdf_tags_paperlyft_table_fixture_contract(filename, table_count):
    html = FakeHTML(filename=resource_path(filename))
    source_cells = [
        element for element in html.etree_element.iter()
        if element.tag.rsplit('}', 1)[-1] in ('th', 'td')]
    source_headers = [
        element for element in source_cells
        if element.tag.rsplit('}', 1)[-1] == 'th']
    source_data = [
        element for element in source_cells
        if element.tag.rsplit('}', 1)[-1] == 'td']
    pdf = html.write_pdf(pdf_tags=True)
    objects = {
        int(number): body for number, body in re.findall(
            rb'(\d+) 0 obj\n(.*?)\nendobj', pdf, re.S)
    }
    found_tables = 0
    table_cells = []
    for body in objects.values():
        if re.search(rb'/S /Table(?:/|>>)', body):
            found_tables += 1
        if re.search(rb'/S /TH(?:/|>>)', body):
            parent_number = int(re.search(rb'/P (\d+) 0 R', body).group(1))
            assert re.search(rb'/S /TR(?:/|>>)', objects[parent_number])
        if re.search(rb'/S /TD(?:/|>>)', body):
            table_cells.append(body)

    assert found_tables == table_count
    assert table_cells
    pdf_header_ids = [
        re.search(rb'/ID \(([^)]*)\)', body).group(1)
        for body in objects.values()
        if re.search(rb'/S /TH(?:/|>>)', body)]
    assert len(pdf_header_ids) == len(source_headers)
    source_to_pdf_id = {
        source_header.attrib['id']: pdf_header_id
        for source_header, pdf_header_id in zip(source_headers, pdf_header_ids)}
    expected_headers = [
        [source_to_pdf_id[token] for token in source_cell.attrib['headers'].split()]
        for source_cell in source_data]
    actual_headers = [
        re.findall(rb'\(([^)]*)\)', re.search(
            rb'/Headers \[([^]]*)\]', body).group(1))
        for body in table_cells]
    assert actual_headers == expected_headers


_STATIC_CONTROL_CUES = {
    'checkbox': ('check box, checked', 'check box, not checked'),
    'radio': ('radio button, selected', 'radio button, not selected'),
}


def _cue(input_type, checked):
    return _STATIC_CONTROL_CUES[input_type][0 if checked else 1]


def _is_static_control(body):
    # A static control is a Span read by its Alt, never a PrintField.
    return bool(re.search(rb'/S /Span(?:/|>>|\s)', body)) and b'/Alt ' in body


def _static_control_alts(pdf):
    return [
        _pdf_text_string(body, b'Alt')
        for body in _pdf_structure_objects(pdf).values() if _is_static_control(body)]


@assert_no_logs
@pytest.mark.parametrize('input_type', ['checkbox', 'radio'])
@pytest.mark.parametrize('checked', [False, True])
@pytest.mark.parametrize('style', [
    '', 'display: inline-block', 'position: absolute; left: 40px',
    'border-style: dashed', 'border-left: 0; border-right: 2px dotted red'])
def test_pdf_tags_static_native_control(input_type, checked, style):
    state = 'checked' if checked else ''
    # Exercise native control appearance from the full UA stylesheet.
    pdf = HTML(string=f'''
      <html lang="en"><title>Static control</title><body>
        <label for="choice">Choice</label>
        <input id="choice" type="{input_type}" style="{style}" {state}>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    controls = [
        (reference, body) for reference, body in objects.items()
        if _is_static_control(body)]
    assert len(controls) == 1
    reference, control = controls[0]
    # Acrobat announces a PrintField as an unavailable, read-only field before
    # any spoken text, and other readers ignore it: the control is text only.
    assert b'/PrintField' not in pdf
    # The label is read where it is printed; the control speaks its state.
    assert _pdf_text_string(control, b'Alt') == _cue(input_type, checked)
    # The control must own actual painted content, not an empty semantic node.
    assert re.search(rb'/K \[\d+(?: |\])', control)
    assert any(
        b'/Nums' in body and reference in body for body in objects.values())
    assert b'/Subtype /Widget' not in pdf
    assert b'/AcroForm' not in pdf


@assert_no_logs
@pytest.mark.parametrize(('lang', 'input_type', 'checked', 'alt', 'alt_lang'), [
    ('en', 'checkbox', True, 'Choice, check box, checked', None),
    ('en-US', 'checkbox', False, 'Choice, check box, not checked', None),
    ('en', 'radio', True, 'Choice, radio button, selected', None),
    ('en', 'radio', False, 'Choice, radio button, not selected', None),
    ('es', 'checkbox', True, 'Choice, casilla de verificación, marcada', None),
    ('es-MX', 'checkbox', False, 'Choice, casilla de verificación, sin marcar', None),
    ('fr', 'checkbox', True, 'Choice, case à cocher, cochée', None),
    ('de', 'radio', False, 'Choice, Optionsfeld, nicht ausgewählt', None),
    ('ja', 'checkbox', True, 'check box, checked', 'en'),
])
def test_pdf_tags_static_native_control_state_is_spoken(
        lang, input_type, checked, alt, alt_lang):
    # A static control is spoken text: its wrapping label, then its state,
    # except where no cues exist.
    state = 'checked' if checked else ''
    pdf = HTML(string=f'''
      <html lang="{lang}"><title>Static control</title><body>
        <label>Choice<input type="{input_type}" {state}></label>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    control = next(body for body in objects.values() if _is_static_control(body))
    assert _pdf_text_string(control, b'Alt') == alt
    if alt_lang is None:
        assert b'/Lang' not in control
    else:
        assert _pdf_text_string(control, b'Lang') == alt_lang


def _pdf_text_string(body, key):
    """Decode a literal or UTF-16 hex PDF text string stored at ``key``."""
    if match := re.search(rb'/' + key + rb' <([0-9a-fA-F]+)>', body):
        data = bytes.fromhex(match.group(1).decode())
        return data[2:].decode('utf-16-be')
    if match := re.search(rb'/' + key + rb' \(((?:[^()\\]|\\.)*)\)', body):
        return re.sub(rb'\\(.)', rb'\1', match.group(1)).decode('latin-1')


def _static_control_paint_owner(objects):
    """Return the control, and the element in its subtree owning the paint."""
    form = next(
        reference for reference, body in objects.items() if _is_static_control(body))
    pending = [form]
    while pending:
        reference = pending.pop()
        body = objects.get(reference, b'')
        if b'/Stm ' in body:
            return form, reference, body
        if children := re.search(rb'/K \[([^]]*)\]', body):
            pending.extend(re.findall(rb'\d+ 0 R', children[1]))


def _static_controls(pdf):
    objects = _pdf_structure_objects(pdf)
    return objects, [
        (reference, body) for reference, body in objects.items()
        if _is_static_control(body)]


@assert_no_logs
@pytest.mark.parametrize(('label', 'input_type', 'checked', 'alt'), [
    ('<label style="display:block">{control} Yes</label>',
     'checkbox', True, 'Yes, check box, checked'),
    ('<label style="display:table"><span style="display:table-cell">{control}'
     '</span><span style="display:table-cell">Yes</span></label>',
     'checkbox', False, 'Yes, check box, not checked'),
    ('<label>{control} Yes</label>', 'radio', True, 'Yes, radio button, selected'),
    # The label's own punctuation already pauses before the state.
    ('<label style="display:block">{control} County Office:</label>',
     'checkbox', False, 'County Office: check box, not checked'),
    ('<label style="display:block">{control} I took office.</label>',
     'checkbox', True, 'I took office. check box, checked'),
    ('<label style="display:block">{control} Other (explain)</label>',
     'checkbox', True, 'Other (explain), check box, checked'),
])
def test_pdf_tags_static_control_label_is_spoken_once(
        label, input_type, checked, alt):
    # A state without its option ("check box, checked") leaves the choice
    # unknown, and a separate label would be read again. A label wrapping
    # one static control is that control: option and state together.
    control = f'<input type="{input_type}" {"checked" if checked else ""}>'
    pdf = HTML(string=f'''
      <html lang="en"><title>Choice</title><body>
        {label.format(control=control)}
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects, controls = _static_controls(pdf)
    assert len(controls) == 1
    reference, control = controls[0]
    assert _pdf_text_string(control, b'Alt') == alt
    assert b'/PrintField' not in pdf
    # The painted box and the label text are both owned by the control.
    assert sorted(_structure_mcids(objects, reference)) == sorted(
        int(mcid) for mcid in re.findall(rb'/MCID (\d+)', pdf))


@assert_no_logs
@pytest.mark.parametrize(('content', 'alt'), [
    ('<label style="display:block"><input type="checkbox">'
     '<del>No</del><span>JB</span></label>',
     'crossed out: No, JB, check box, not checked'),
    ('<label style="display:block"><input type="checkbox">'
     'Yes, how many <del>&nbsp;</del> JB</label>',
     'Yes, how many crossed out, JB, check box, not checked'),
    ('<p><del><label>No<input type="checkbox"></label></del></p>',
     'crossed out: No, check box, not checked'),
])
def test_pdf_tags_static_control_label_speaks_crossed_out_words(content, alt):
    pdf = HTML(string=f'''
      <html lang="en"><title>Correction</title><body>{content}</body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert _static_control_alts(pdf) == [alt]


@assert_no_logs
@pytest.mark.parametrize(('content', 'lang', 'alt'), [
    # Wrapped across lines, the label has one box per line.
    ('<p style="width:60px"><label>Choice one two three four five'
     '<input type="checkbox"></label></p>', 'en', 'check box, not checked'),
    # A link inside the label needs its own structure owner.
    ('<label style="display:block"><input type="checkbox">'
     '<a href="#terms">Terms</a></label><p id="terms">Terms</p>',
     'en', 'check box, not checked'),
    # The control is named by its own attribute, which nothing else reads.
    ('<label style="display:block"><input type="checkbox" '
     'aria-label="Spoken">Visible</label>', 'en', 'Spoken, check box, not checked'),
    # No spoken cues exist for this language.
    ('<label style="display:block"><input type="checkbox">Sentaku</label>',
     'ja', 'check box, not checked'),
])
def test_pdf_tags_static_control_label_kept_separate(content, lang, alt):
    # The label text stays where it is printed and is read there.
    pdf = HTML(string=f'''
      <html lang="{lang}"><title>Choice</title><body>{content}</body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert _static_control_alts(pdf) == [alt]


@assert_no_logs
@pytest.mark.parametrize(('tag', 'subtype'), [
    ('footer', b'/Footer'), ('header', b'/Header')])
def test_pdf_tags_hidden_page_furniture_is_pagination_artifact(tag, subtype):
    # Running page furniture hidden from assistive technology in HTML is
    # painted as a pagination artifact and kept out of the structure tree.
    pdf = HTML(string=f'''
      <html lang="en"><title>Furniture</title><body>
        <p>Body text</p>
        <{tag} aria-hidden="true"><p>Page 1</p><span>Form rev. 2023</span></{tag}>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    artifacts = re.findall(
        rb'/Artifact\s*<</Type /Pagination\s*/Subtype (/\w+)>>\s*BDC(.*?)EMC',
        pdf, re.S)
    assert len(artifacts) == 2
    assert all(found == subtype and b'TJ' in body for found, body in artifacts)
    assert len(re.findall(rb'/MCID \d+', pdf)) == 1
    assert not re.search(rb'/S /(?:P|Span|NonStruct)(?:/|>>)[^\n]*Page 1', pdf)
    assert not re.search(rb'/S /Div(?:/|>>)', pdf)


@assert_no_logs
def test_pdf_tags_hidden_generic_content_is_an_artifact():
    pdf = HTML(string='''
      <html lang="en"><title>Hidden</title><body>
        <p>Body text</p><div aria-hidden="true">Decorative glyphs</div>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert re.search(rb'/Artifact\s+BMC[^E]*TJ', pdf)
    assert len(re.findall(rb'/MCID \d+', pdf)) == 1


@assert_no_logs
@pytest.mark.parametrize('content', [
    '<a href="https://example.com/">Link</a>',
    '<label>Choice<input type="checkbox" checked></label>',
])
def test_pdf_tags_hidden_content_with_annotations_stays_semantic(content):
    # Links and widgets need a structure owner, so their subtree stays tagged.
    pdf = HTML(string=f'''
      <html lang="en"><title>Hidden</title><body>
        <p>Body text</p><footer aria-hidden="true">{content}</footer>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert b'/Pagination' not in pdf
    assert len(re.findall(rb'/MCID \d+', pdf)) >= 2


@assert_no_logs
@pytest.mark.parametrize(('lang', 'tag', 'actual_text'), [
    ('en', 'del', 'crossed out: No'),
    ('en', 's', 'crossed out: No'),
    ('en', 'strike', 'crossed out: No'),
    ('es', 'del', 'tachado: No'),
])
def test_pdf_tags_line_through_text_is_spoken(lang, tag, actual_text):
    pdf = HTML(string=f'''
      <html lang="{lang}"><title>Correction</title><body>
        <p>Answer: <{tag}>No</{tag}> PB</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    struck = [
        body for body in objects.values()
        if b'/TextDecorationType /LineThrough' in body]
    assert len(struck) == 1
    assert re.search(rb'/S /Span(?:/|>>)', struck[0])
    assert b'/O /Layout' in struck[0]
    assert _pdf_text_string(struck[0], b'ActualText') == actual_text


@assert_no_logs
def test_pdf_tags_line_through_blank_is_spoken():
    # A struck-out blank is visible content: its line is painted, so the
    # element keeps tagged content and says that something was crossed out.
    pdf = HTML(string='''
      <html lang="en"><title>Correction</title><body>
        <p>How many <del>&nbsp;&nbsp;&nbsp;</del> JB</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    struck = next(
        (reference, body) for reference, body in objects.items()
        if b'/TextDecorationType /LineThrough' in body)
    assert _pdf_text_string(struck[1], b'ActualText') == 'crossed out'
    assert re.search(rb'/K \[\d+ 0 R', struck[1])


@assert_no_logs
def test_pdf_tags_line_through_never_hides_a_control_or_image():
    # ActualText replaces every descendant, which would silence a check box
    # state or an image alternative inside the struck element.
    image_url = path2url(resource_path('pattern.png'))
    pdf = HTML(string=f'''
      <html lang="en"><title>Correction</title><body>
        <p><del><label>No<input type="checkbox"></label></del></p>
        <p><s><img src="{image_url}" alt="Initials"> PB</s></p>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert pdf.count(b'/TextDecorationType /LineThrough') == 2
    assert b'/ActualText' not in pdf
    assert _static_control_alts(pdf) == ['crossed out: No, check box, not checked']


@assert_no_logs
def test_pdf_tags_line_through_without_known_language_keeps_attribute_only():
    pdf = HTML(string='''
      <html lang="ja"><title>Correction</title><body><p><del>No</del></p></body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert b'/TextDecorationType /LineThrough' in pdf
    assert b'/ActualText' not in pdf


@assert_no_logs
@pytest.mark.parametrize('note', [
    '<p id="fn1" role="doc-footnote">1 Footnote text</p>',
    '<aside id="fn1" role="doc-footnote"><p>1 Footnote text</p></aside>',
])
def test_pdf_tags_footnote_is_note_with_registered_id(note):
    pdf = HTML(string=f'''
      <html lang="en"><title>Notes</title><body>
        <p>Body<sup role="doc-noteref">1</sup> text</p>{note}
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    notes = [
        (reference, body) for reference, body in objects.items()
        if re.search(rb'/S /Note(?:/|>>)', body)]
    assert len(notes) == 1
    reference, body = notes[0]
    assert b'/ID (fn1)' in body
    id_tree = objects[re.search(rb'/IDTree (\d+ 0 R)', pdf).group(1)]
    assert re.search(rb'\(fn1\) ' + reference, id_tree)
    assert len(re.findall(rb'/S /Reference(?:/|>>)', pdf)) == 1


@assert_no_logs
@pytest.mark.parametrize(('link', 'contents'), [
    ('<a href="#fn1" role="doc-noteref">1</a>', '1'),
    ('<a href="#fn1" aria-label="Footnote 1">1</a>', 'Footnote 1'),
    ('<a href="#fn1"> Note\n one </a>', 'Note one'),
    ('<a href="https://example.com/">Example</a>', 'https://example.com/'),
])
def test_pdf_tags_internal_link_contents_describe_the_link(link, contents):
    # An internal link's description is its accessible text, not the
    # destination name, which is an identifier that merging may rename.
    pdf = HTML(string=f'''
      <html lang="en"><title>Links</title><body>
        <p>Body{link}</p><p id="fn1">1 Note</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    annotation = next(
        body for body in _pdf_structure_objects(pdf).values()
        if b'/Subtype /Link' in body)
    assert _pdf_text_string(annotation, b'Contents') == contents


@assert_no_logs
@pytest.mark.parametrize(('label', 'alt'), [
    (' aria-label=" Footnote  1 "', 'Footnote 1'), ('', None)])
def test_pdf_tags_link_aria_label_is_its_alternate_description(label, alt):
    # The accessible name of a link replaces its text for assistive technology.
    pdf = HTML(string=f'''
      <html lang="en"><title>Links</title><body>
        <p>Body<a href="#fn1"{label}>1</a></p><p id="fn1">1 Note</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    link = next(
        body for body in _pdf_structure_objects(pdf).values()
        if re.search(rb'/S /Link(?:/|>>)', body))
    assert _pdf_text_string(link, b'Alt') == alt


@assert_no_logs
def test_pdf_tags_footnote_without_id_gets_unique_id():
    pdf = HTML(string='''
      <html lang="en"><title>Notes</title><body>
        <p role="doc-footnote">1 First</p><p role="doc-footnote">2 Second</p>
      </body></html>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    ids = [
        re.search(rb'/ID \(([^)]+)\)', body).group(1)
        for body in objects.values() if re.search(rb'/S /Note(?:/|>>)', body)]
    assert len(ids) == len(set(ids)) == 2


@assert_no_logs
@pytest.mark.parametrize('zoom', [1, 2])
def test_pdf_tags_figure_bbox_uses_pdf_user_space(zoom):
    image_url = path2url(resource_path('pattern.png'))
    pdf = FakeHTML(string=f'''
      <html lang="en"><body>
        <style>@page {{ size: 400px 300px; margin: 0 }}</style>
        <img src="{image_url}" alt="image"
             style="position:absolute;left:96px;top:96px;width:96px;height:48px">
      </body></html>
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True, zoom=zoom)
    bbox = [float(value) for value in re.search(
        rb'/BBox \[([^]]*)\]', pdf).group(1).split()]
    scale = 0.75 * zoom
    assert bbox == pytest.approx([
        96 * scale, (300 - 144) * scale, 192 * scale, (300 - 96) * scale])


@assert_no_logs
@pytest.mark.parametrize(('content', 'alt'), [
    ('<label><strong>Choice</strong><input type="checkbox"></label>',
     'Choice, check box, not checked'),
    # A label in another cell is read in its cell, not again by the control.
    ('<table><tr><td><label for="x"><em>Choice</em></label></td>'
     '<td><input id="x" type="checkbox"></td></tr></table>', 'check box, not checked'),
    ('<div style="display:table"><span style="display:table-cell">'
     '<label for="x">Choice</label></span><span style="display:table-cell">'
     '<input id="x" type="checkbox"></span></div>', 'check box, not checked'),
])
def test_pdf_tags_static_native_control_labels(content, alt):
    pdf = HTML(string=f'<html lang="en"><title>Controls</title>{content}').write_pdf(
        pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert _static_control_alts(pdf) == [alt]


@assert_no_logs
@pytest.mark.parametrize('style', ['display:none', 'visibility:hidden'])
def test_pdf_tags_static_native_control_hidden(style):
    pdf = HTML(string=f'''
      <html lang="en"><title>Hidden control</title><p>Visible text</p>
      <input type="checkbox" style="{style}">
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert _static_control_alts(pdf) == []


@assert_no_logs
@pytest.mark.parametrize('appearance', ['', '''
    input {border:none;background:transparent}
    input::before {content:"";border:2px solid black;opacity:.6}
    input::after {content:none}'''])
def test_pdf_tags_static_native_control_repeated_header(appearance):
    rows = ''.join(f'<tr><td>Row {index}</td></tr>' for index in range(8))
    pdf = HTML(string=f'''
      <html lang="en"><title>Repeated control</title>
      <style>@page {{ size: 200px 120px; margin: 5px }}
      td, th {{ height: 35px }}{appearance}</style>
      <table><thead><tr><th><label>Choice<input type="checkbox" checked>
      </label></th></tr></thead><tbody>{rows}</tbody></table>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert len(re.findall(rb'/Type /Page\b', pdf)) > 1
    # The repeated label has a box on each page, so it is read in place.
    assert _static_control_alts(pdf) == ['check box, checked']


@assert_no_logs
def test_pdf_tags_static_native_control_keeps_generated_text():
    pdf = HTML(string='''
      <html lang="en"><title>Control content</title>
      <style>input::before { content: "X"; } input::after { content: "Y"; }</style>
      <p>Before</p><label>Choice<input type="checkbox" checked></label><p>After</p>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    control = next(body for body in objects.values() if _is_static_control(body))
    children = re.findall(rb'\d+ 0 R', re.search(rb'/K \[([^]]*)\]', control)[1])
    assert len(children) == 2
    assert pdf.count(b'/MCID') >= 6
    assert len(_static_control_alts(pdf)) == 1


@assert_no_logs
@pytest.mark.parametrize('checked', [False, True])
@pytest.mark.parametrize('style', ['', 'border:none;background:red',
    'border:none;background:transparent;box-shadow:0 0 0 3px black;'
    'outline:2px solid red',
    'border:3px solid transparent;border-image:linear-gradient(red, blue) 1'])
def test_pdf_tags_static_native_control_leaves_interactive_mode(checked, style):
    state = 'checked' if checked else ''
    pdf = HTML(string=f'''
      <html lang="en"><title>Interactive control</title>
      <form><label for="choice">Choice</label>
      <input id="choice" name="choice" type="checkbox" style="{style}" {state}></form>
    ''').write_pdf(pdf_tags=True, pdf_forms=True, uncompressed_pdf=True)
    assert len(re.findall(rb'/S /Form(?:/|>>)', pdf)) == 1
    assert b'/O /PrintField' not in pdf
    assert b'/Subtype /Widget' in pdf
    assert b'/TU (Choice)' in pdf
    assert f'/V /{"on" if checked else "Off"}'.encode() in pdf


@assert_no_logs
@pytest.mark.parametrize('content', [
    '<label for="other">Wrong<input id="choice" type="checkbox"></label>'
    '<label for="choice">Right choice</label><input id="other">',
    '<label for="choice"><strong>Right</strong> choice</label>'
    '<div style="break-before:page"><input id="choice" type="checkbox"></div>',
])
def test_pdf_tags_static_native_control_label_association(content):
    # "Right choice" is read where it is printed; "Wrong" labels another control.
    pdf = HTML(string=f'<html lang="en"><title>Labels</title>{content}').write_pdf(
        pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert _static_control_alts(pdf) == ['check box, not checked']


@assert_no_logs
def test_pdf_tags_static_native_control_running_copies():
    pdf = HTML(string='''
      <html lang="en"><title>Running controls</title><style>
      @page { @top-center { content:element(control) }
              @bottom-center { content:element(control) } }
      .running { position:running(control) }
      </style><div class="running"><label>Choice<input type="checkbox"></label></div>
      <p>First</p><p style="break-before:page">Second</p>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert len(re.findall(rb'/Type /Page\b', pdf)) == 2


@assert_no_logs
@pytest.mark.parametrize(('content', 'name'), [
    # Names printed and read elsewhere are not spoken again.
    ('<label for="x">First</label><label for="x"><b>Second</b></label>'
     '<input id="x" type="checkbox">', None),
    ('<label>Wrong<input type="text"><input type="checkbox" '
     'title="Right"></label>', 'Right'),
    ('<label for="missing">Wrong<input type="checkbox" '
     'title="Right"></label>', 'Right'),
    ('<label for="x">Visible</label><input id="x" type="checkbox" '
     'aria-label="Spoken">', 'Spoken'),
    ('<span id="a">First <b>nested</b></span><span id="b">Second</span>'
     '<input type="checkbox" aria-label="Wrong" aria-labelledby="b a">', None),
    ('<input type="checkbox" aria-labelledby="missing" aria-label="Right">',
     'Right'),
    ('<span id="a" hidden>Hidden name</span>'
     '<input type="checkbox" aria-labelledby="a">', 'Hidden name'),
    ('<label><img alt="Image choice"><input type="checkbox"></label>',
     'Image choice'),
    # The PDF reads the reference's text, not its aria-label.
    ('<span id="a" aria-label="Spoken reference">Wrong</span>'
     '<input type="checkbox" aria-labelledby="a">', 'Spoken reference'),
    ('<style>.hidden{display:none}</style><label>Right'
     '<span class="hidden">Wrong</span><span hidden>Wrong</span>'
     '<span aria-hidden="true">Wrong</span><input type="checkbox"></label>',
     'Right'),
    # A label spanning several boxes is read in place.
    ('<label>First<span style="display:block">Second</span>Third'
     '<input type="checkbox"></label>', None),
    ('<label for="x"><span style="visibility:hidden">Excluded'
     '<span style="visibility:visible">Visible name</span></span></label>'
     '<input id="x" type="checkbox">', None),
    ('<label for="x" hidden>Hidden label</label>'
     '<input id="x" type="checkbox">', 'Hidden label'),
])
def test_pdf_tags_static_native_control_accessible_name(content, name):
    pdf = HTML(string=f'<html lang="en"><title>Names</title>{content}').write_pdf(
        pdf_tags=True, uncompressed_pdf=True)
    cue = 'check box, not checked'
    assert _static_control_alts(pdf) == [f'{name}, {cue}' if name else cue]


@assert_no_logs
@pytest.mark.parametrize('content', [
    '<input type="checkbox" aria-hidden="true">',
    '<div aria-hidden="true"><input type="radio" checked></div>',
    '<div aria-hidden="true"><input type="checkbox" aria-hidden="false"></div>',
])
def test_pdf_tags_static_native_control_aria_hidden(content):
    pdf = HTML(string=f'<html lang="en"><title>Hidden semantics</title>'
               f'<p>Visible text</p>{content}').write_pdf(
                   pdf_tags=True, uncompressed_pdf=True)
    assert _static_control_alts(pdf) == []
    assert not re.search(rb'/S /Form(?:/|>>)', pdf)


@assert_no_logs
@pytest.mark.parametrize(('style', 'painted'), [
    ('border:none;background:transparent', False),
    ('border-color:transparent;background:transparent', False),
    ('border:none;background:red', True),
    ('border:none;background:linear-gradient(red, blue)', True),
    ('border:none;background:linear-gradient(red, blue) no-repeat', True),
    ('border:none;background:url(pattern.png)', True),
    ('border:none;background:url(pattern.png) no-repeat', True),
    ('border:none;background:linear-gradient(red, blue);background-size:0 0', False),
    ('border:3px solid transparent;border-image:linear-gradient(red, blue) 1', True),
    ('border:3px solid transparent;border-image:linear-gradient(red, blue) 1;'
     'border-image-width:0;background:transparent', False),
    ('background:red;border:2px solid blue', True),
])
@pytest.mark.parametrize('layout', [
    '', 'display:block', 'position:absolute', 'display:table-cell'])
@pytest.mark.parametrize('input_type', ['checkbox', 'radio'])
def test_pdf_tags_static_native_control_custom_paint(
        style, painted, layout, input_type):
    html = HTML(base_url=resource_path(''), string=f'''
      <html lang="en"><title>Custom control</title>
      <label>Choice<input type="{input_type}" style="{style};{layout}"></label>''')
    assert html.write_pdf().startswith(b'%PDF-')
    pdf = html.write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert len(_static_control_alts(pdf)) == int(painted)
    appearances = re.findall(rb'/Form\s+<</MCID (\d+)>>\s+BDC(.*?)EMC', pdf, re.S)
    assert len(appearances) == int(painted)
    if painted:
        assert b'/Artifact' not in appearances[0][1]
        assert re.search(rb'\b(?:f\*?|S|Do|sh)\b', appearances[0][1])


@assert_no_logs
@pytest.mark.parametrize(('style', 'extra'), [
    ('background:red;border:2px solid blue;box-shadow:inset 2px 2px 2px black', ''),
    ('background:red;border:2px solid blue;opacity:.6;'
     'box-shadow:inset 2px 2px 2px black,3px 3px 2px black', ''),
    ('display:block;width:180px;height:50px;column-count:2;'
     'column-rule:2px solid green;background:red;border:2px solid blue',
     'input::before {content:"One two three four five six seven eight nine ten"}'),
])
@pytest.mark.parametrize('input_type', ['checkbox', 'radio'])
@pytest.mark.parametrize('checked', [False, True])
def test_pdf_tags_static_native_control_decorations(style, extra, input_type, checked):
    state = 'checked' if checked else ''
    pdf = HTML(string=f'''<html lang="en"><title>Control decorations</title>
      <style>{extra}</style><div style="opacity:.7"><label>Choice
      <input type="{input_type}" {state} style="{style}"></label></div>
    ''').write_pdf(pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert len(_static_control_alts(pdf)) == 1
    appearances = list(re.finditer(
        rb'/Form\s+<</MCID \d+>>\s+BDC(.*?)EMC', pdf, re.S))
    assert len(appearances) == 1
    appearance, = appearances
    # PDF/UA-1 7.1 forbids artifact/tagged-content nesting. A real painted
    # component owns the Form; subsequent decoration must stay outside it.
    assert b'/Artifact' not in appearance[1]
    assert re.search(rb'\bf\b', appearance[1])
    assert re.search(rb'/Artifact\s+BMC.*?\bf\*?\b.*?EMC',
                     pdf[appearance.end():], re.S)
    objects = _pdf_structure_objects(pdf)
    _, reference, control = _static_control_paint_owner(objects)
    stream_reference = re.search(rb'/Stm (\d+ 0 R)', control)[1]
    assert b'/StructParents ' in objects[stream_reference]
    assert any(b'/Nums' in body and reference in body for body in objects.values())


@assert_no_logs
@pytest.mark.parametrize(('style', 'painted'), [
    ('box-shadow:0 0 0 3px black', True),
    ('box-shadow:inset 0 0 0 3px black', True),
    ('outline:3px solid black;outline-offset:2px', True),
    ('box-shadow:0 0 0 3px transparent', False),
    ('box-shadow:0 0 0 0 black', False),
    ('box-shadow:inset 0 0 0 0 black', False),
    ('outline:0 solid black', False),
])
@pytest.mark.parametrize('input_type', ['checkbox', 'radio'])
@pytest.mark.parametrize('checked', [False, True])
def test_pdf_tags_static_native_control_shadow_outline(
        style, painted, input_type, checked):
    pdf = HTML(string=f'''<html lang="en"><title>Control appearance</title>
      <style>input::before,input::after {{content:none}}</style>
      <div style="opacity:.7"><input type="{input_type}" aria-label="Choice"
      {'checked' if checked else ''} style="border:none;background:transparent;
      width:24px;height:24px;opacity:.6;{style}"></div>
    ''').write_pdf(pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    alts = _static_control_alts(pdf)
    assert alts == ([f'Choice, {_cue(input_type, checked)}'] if painted else [])
    assert len(re.findall(rb'/Form\s+<</MCID \d+>>\s+BDC', pdf)) == int(painted)
    if painted:
        appearance = re.search(rb'/Form\s+<</MCID \d+>>\s+BDC(.*?)EMC', pdf, re.S)
        assert b'/Artifact' not in appearance[1]
        assert re.search(rb'\b(?:f|f\*|S|sh)\b', appearance[1])


@assert_no_logs
@pytest.mark.parametrize(('content', 'marker'), [
    ('"X"', 'Span'), ('url(pattern.png)', 'Figure')])
@pytest.mark.parametrize('input_type', ['checkbox', 'radio'])
@pytest.mark.parametrize('checked', [False, True])
def test_pdf_tags_static_native_control_tagged_descendant(
        content, marker, input_type, checked):
    pdf = HTML(base_url=resource_path(''), string=f'''
      <html lang="en"><title>Descendant control</title><style>
      input {{border:none;background:transparent;width:24px;height:24px}}
      input::before {{content:{content};background:transparent;color:black}}
      input::after {{content:none}}
      </style><div style="opacity:.7"><input type="{input_type}" aria-label="Choice"
      {'checked' if checked else ''} style="opacity:.6"></div>
    ''').write_pdf(pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    controls = [body for body in objects.values() if _is_static_control(body)]
    assert len(controls) == 1
    control, = controls
    assert _pdf_text_string(control, b'Alt') == f'Choice, {_cue(input_type, checked)}'
    # The existing child owns its MCID. The native parent adds structure and
    # attributes only, never a second or empty marked-content sequence.
    assert not re.search(rb'/Form\s+<</MCID', pdf)
    assert len(re.findall(rb'/MCID \d+', pdf)) == 2  # BDC and its MCR.
    assert re.search(fr'/{marker}\s+<</MCID \d+>>\s+BDC'.encode(), pdf)
    children = re.search(rb'/K \[([^]]*)\]', control)[1]
    assert re.fullmatch(rb'(?:\d+ 0 R\s*)+', children)


@assert_no_logs
@pytest.mark.parametrize('style', ['visibility:hidden', 'font-size:0', ''])
def test_pdf_tags_static_native_control_empty_descendant(style):
    content = '"X"' if style else '""'
    pdf = HTML(string=f'''<html lang="en"><title>Empty descendant</title><style>
      input {{border:none;background:transparent}}
      input::before {{content:{content};{style}}} input::after {{content:none}}
      </style><p>Text</p><input type="checkbox" aria-label="Choice">
    ''').write_pdf(pdf_tags=True, uncompressed_pdf=True)
    assert _static_control_alts(pdf) == []


@assert_no_logs
@pytest.mark.parametrize('pseudo', ['before', 'after', 'native'])
@pytest.mark.parametrize('input_type', ['checkbox', 'radio'])
@pytest.mark.parametrize('checked', [False, True])
@pytest.mark.parametrize('opacity', ['', 'opacity:.6'])
def test_pdf_tags_static_native_control_pseudo_paint(
        pseudo, input_type, checked, opacity):
    extra = '' if pseudo == 'native' else f'''
      input::before,input::after {{content:none}}
      input::{pseudo} {{content:"";display:block;width:20px;height:20px;
        border:2px solid black;opacity:.8}}'''
    pdf = HTML(string=f'''<html lang="en"><title>Pseudo control</title><style>
      input {{border:none;background:transparent;width:24px;height:24px}}
      {extra}</style><div style="opacity:.7"><input type="{input_type}"
      aria-label="Choice" {'checked' if checked else ''} style="{opacity}"></div>
    ''').write_pdf(pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    painted = pseudo != 'native' or checked
    alts = _static_control_alts(pdf)
    assert alts == ([f'Choice, {_cue(input_type, checked)}'] if painted else [])
    appearances = re.findall(rb'/Form\s+<</MCID \d+>>\s+BDC(.*?)EMC', pdf, re.S)
    assert len(appearances) == int(painted)
    if painted:
        assert b'/Artifact' not in appearances[0]
        # A filled shape, or the check mark image of a checked checkbox.
        assert re.search(rb'\b(?:f|Do)\b', appearances[0])


@assert_no_logs
@pytest.mark.parametrize('extra', [
    'input {visibility:hidden}', 'input::before {visibility:hidden}',
    'input::before {border:none;background:transparent}',
])
def test_pdf_tags_static_native_control_pseudo_no_paint(extra):
    pdf = HTML(string=f'''<html lang="en"><title>No pseudo paint</title><style>
      input {{border:none;background:transparent}}
      input::before {{content:"";display:block;width:20px;height:20px;
        border:2px solid black}} input::after {{content:none}} {extra}
      </style><p>Text</p><input type="checkbox" aria-label="Choice">
    ''').write_pdf(pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert _static_control_alts(pdf) == []


@assert_no_logs
@pytest.mark.parametrize('appearance', [
    'border:none;background:transparent',
    'border:2px solid blue;background:red;box-shadow:inset 0 0 0 3px black',
])
def test_pdf_tags_static_native_control_pseudo_layout_owners(appearance):
    pdf = HTML(string=f'''<html lang="en"><title>Distinct controls</title><style>
      input {{{appearance};outline:2px solid green}}
      input::before,input::after {{content:"X";display:block;
        width:20px;height:20px;border:2px solid black;opacity:.6}}
      </style><div style="opacity:.7"><input type="checkbox" aria-label="First"
      ><input type="checkbox" checked aria-label="Second"></div>
    ''').write_pdf(pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    assert sorted(_static_control_alts(pdf)) == [
        'First, check box, not checked', 'Second, check box, checked']
    assert len(re.findall(rb'/Form\s+<</MCID \d+>>\s+BDC', pdf)) == 2
    assert len(re.findall(rb'/Span\s+<</MCID \d+>>\s+BDC', pdf)) == 4


@assert_no_logs
@pytest.mark.parametrize('style', ['opacity:.5', 'opacity:.5;position:absolute'])
@pytest.mark.parametrize('appearance', ['', 'border:none;background:red',
    'border:3px solid transparent;border-image:linear-gradient(red, blue) 1'])
def test_pdf_tags_static_native_control_nested_opacity(style, appearance):
    pdf = HTML(string=f'''
      <html lang="en"><title>Opacity control</title>
      <div style="opacity:.5"><label>Choice<input type="checkbox" checked
      style="{style};{appearance}"></label></div>
    ''').write_pdf(pdf_tags=True, pdf_variant='pdf/ua-1', uncompressed_pdf=True)
    objects = _pdf_structure_objects(pdf)
    _, reference, control = _static_control_paint_owner(objects)
    stream = re.search(rb'/Stm (\d+ 0 R)', control)
    assert stream
    group = objects[stream[1]]
    assert b'/Subtype /Form' in group
    assert b'/StructParents ' in group
    assert b'/MCID' in group
    assert len(re.findall(rb'/Form\s+<</MCID \d+>>\s+BDC', group)) == 1
    assert any(b'/Nums' in body and reference in body for body in objects.values())


@pytest.mark.parametrize(('html', 'fields'), [
    ('<input>', ['/Tx', '/V ()']),
    ('<input value="">', ['/Tx', '/V ()']),
    ('<input type="checkbox">', ['/Btn']),
    ('<input type="radio">',
     ['/Btn', '/V /Off', '/AS /Off', '/Ff 49152']),
    ('<input checked type="radio" name="foo" value="value">',
     ['/Btn', '/T (foo)', '/V /0', '/AS /0']),
    ('<form><input type="radio" name="foo" value="v0"></form>'
     '<form><input checked type="radio" name="foo" value="v1"></form>',
     ['/Btn', '/AS /0', '/V /0', '/AS /Off', '/V /Off']),
    ('<textarea></textarea>', ['/Tx', '/V ()']),
    ('<select><option value="a">A</option></select>', ['/Ch', '/Opt']),
    ('<select>'
     '<option value="a">A</option>'
     '<option value="b" selected>B</option>'
     '</select>', ['/Ch', '/Opt', '/V (b)']),
    ('<select multiple>'
     '<option value="a">A</option>'
     '<option value="b" selected>B</option>'
     '<option value="c" selected>C</option>'
     '</select>', ['/Ch', '/Opt', '[(b) (c)]']),
    ('<form><input name=name>', ['/TU (name)']),
    ('<form><input name=name id=input>', ['/TU (name)']),
    ('<form><input name=name placeholder=placeholder>', ['/TU (placeholder)']),
    ('<form><input placeholder=placeholder title=title>', ['/TU (title)']),
    ('<form><label for=input>\nLabel\n</label><input id=input>', ['/TU (Label)']),
    ('<form><label>\nLabel\n<input name=name id=input>', ['/TU (Label)']),
    ('<form><label><input name=name> Label </label>', ['/TU (Label)']),
])
def test_pdf_forms(html, fields):
    pdf = FakeHTML(string=html).write_pdf(pdf_forms=True, uncompressed_pdf=True)
    assert b'AcroForm' in pdf
    for field in fields:
        assert field.encode() in pdf


@assert_no_logs
def test_pdf_ua_2_namespace_type():
    # Regression test for #2786.
    pdf = FakeHTML(string='<html lang="en"><body>abc').write_pdf(
        pdf_variant='pdf/ua-2', uncompressed_pdf=True)
    assert b'/Type /Namespace' in pdf


@assert_no_logs
def test_svg_gradient_color_ops_before_path():
    # Regression test for #2762. SVG gradient color-setting operators
    # (CS/SCN) must appear before path-construction operators (m/l/c/re),
    # per ISO 32000-1 §8.5.2.1 — color operators are forbidden in the
    # path object state.
    pdf = FakeHTML(string='''
      <svg viewBox="0 0 100 10" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id="g">
            <stop stop-color="transparent" offset="0"/>
            <stop stop-color="#008dd4" offset="1"/>
          </linearGradient>
        </defs>
        <path d="M 0,5 h 100" fill="none" stroke="url(#g)" stroke-width="10"/>
      </svg>
    ''').write_pdf()
    cs_offset = pdf.find(b'/Pattern CS')
    assert cs_offset != -1
    lineto_offset = pdf.find(b'100 5 l')
    assert lineto_offset != -1
    assert cs_offset < lineto_offset


@assert_no_logs
def test_links_note():
    pdf = FakeHTML(string='''
      <style>
        @page {
          @note-area {
            content: element(sidenotes, all-once);
          }
        }
        span {
          display: block;
          position: note(sidenotes);
        }
      </style>
      <div>abc<span>de</span>fgh<span>ij</span></div>''').write_pdf()
    assert b'/Dest (note-1)' in pdf
