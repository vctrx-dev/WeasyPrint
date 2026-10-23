"""Test the user-agent stylesheet."""

import pytest

from weasyprint import HTML
from weasyprint.html import CSS, PH, UA, UA_FORM

from ..testing_utils import assert_no_logs


@assert_no_logs
@pytest.mark.parametrize('css', [UA, UA_FORM, PH])
def test_ua_stylesheets(css):
    CSS(string=css)


@assert_no_logs
@pytest.mark.parametrize(('input_type', 'check_mark'), [
    ('checkbox', True), ('radio', False)])
def test_ua_checked_control_indicator(input_type, check_mark):
    # Like browsers, a checked checkbox shows a check mark, not a filled
    # square; a selected radio button keeps its filled dot.
    document = HTML(string=f'<input type="{input_type}" checked>').render()
    marker = next(
        box for box in document.pages[0]._page_box.descendants()
        if box.element_tag == 'input::before')
    (image_type, image), = marker.style['background_image']
    if check_mark:
        assert image_type == 'url'
        assert image.startswith('data:image/svg+xml')
        assert marker.style['background_color'].alpha == 0
    else:
        assert image_type == 'none'
        assert marker.style['background_color'].alpha == 1
