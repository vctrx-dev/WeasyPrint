"""Regression tests for security fixes backported from WeasyPrint 70."""

from base64 import b64encode

from PIL import EpsImagePlugin

from .testing_utils import FakeHTML, capture_logs


def test_eps_never_launches_ghostscript(monkeypatch):
    calls = []

    def reject_process(*args, **kwargs):
        calls.append(args)
        raise AssertionError('An untrusted image must not launch an interpreter')

    monkeypatch.setattr(EpsImagePlugin.subprocess, 'check_call', reject_process)
    monkeypatch.setattr(EpsImagePlugin.subprocess, 'Popen', reject_process)
    eps = b'%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 1 1\nshowpage\n'
    url = f'data:image/x-eps;base64,{b64encode(eps).decode()}'
    with capture_logs() as logs:
        pdf = FakeHTML(string=f'<img src="{url}">').write_pdf()
    assert pdf.startswith(b'%PDF-')
    assert not calls
    assert any('Failed to load image' in log for log in logs)
