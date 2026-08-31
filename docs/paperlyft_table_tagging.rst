PaperLyft PDF/UA Table Tagging
==============================

Purpose
-------

PaperLyft renders semantic HTML tables as tagged PDF/UA-1 documents. The PDF
structure tree must preserve the HTML table's spans, header scopes, and header
associations even when these attributes do not change the painted page.

This fork keeps the correction standards-based and inside WeasyPrint's PDF
tagging boundary. It does not contain OCR, source-document interpretation, or
PaperLyft workflow behavior.

Verified Schedule B(1) Regression
---------------------------------

The regression was verified with an Arizona Schedule B(1) operating-expense
table reconstructed from source page 4. The semantic table contained five
columns, five recipient rows, and a footer whose row header used
``colspan="3"``. Column headers used ``scope="col"``, row headers used
``scope="row"``, and data cells had 22 resolved header associations.

The exact same accepted HTML, fonts, adapter, PDF/UA options, and WeasyPrint
69.0 version were rendered with the published package and this fork. The
rendered page rasters had identical SHA-256 hashes, proving that the patch did
not change appearance.

===========================  ====================  ====================
Check                        Published 69.0        PaperLyft fork
===========================  ====================  ====================
Rendered pages               1 Letter page         1 Letter page
Raster output                Identical              Identical
veraPDF PDF/UA-1             Failed                 Passed
``/ColSpan`` attributes      0                      1
``/Scope /Column`` values    0                      5
``/Scope /Row`` values       0                      6
``/Headers`` arrays          22                     22
===========================  ====================  ====================

The published package failed ISO 14289-1:2014 clause 7.2, test 43. veraPDF
reported that rows 1 and 7 spanned different numbers of columns: five and
three. The HTML footer was correct, but without ``/ColSpan 3`` in the PDF
structure attributes, the validator counted its spanning header as one cell.
This fork emits the span, so the footer has the same effective five-column
width as the other rows.

Implemented Behavior
--------------------

The table-tagging implementation is in ``weasyprint/pdf/tags.py``. It:

* emits ``/ColSpan`` and ``/RowSpan`` from the laid-out semantic table cell;
* emits PDF-native ``/Scope /Column`` and ``/Scope /Row`` values for HTML
  ``scope="col"`` and ``scope="row"`` headers;
* resolves ``scope="colgroup"`` and ``scope="rowgroup"`` relationships into
  concrete ``/Headers`` associations, because PDF/UA-1 has no corresponding
  grouped ``/Scope`` names;
* resolves explicit HTML ``headers`` tokens only to real header cells in the
  same table, preserves source order, and removes duplicate tokens;
* uses the layout cell's ``grid_x``, ``colspan``, and ``rowspan`` instead of
  reconstructing a second table grid in the PDF layer; and
* retains header identities across page fragments so repeated and split tables
  reference headers from the correct table.

Regression Coverage
-------------------

Focused tag-tree tests are in ``tests/test_pdf.py``. Realistic PaperLyft table
fixtures are under ``tests/resources/`` and include:

* ``paperlyft_schedule_b1_disbursements.html`` for grouped recipient rows,
  row and column spans, totals, and explicit header relationships;
* ``paperlyft_campaign_transactions.html`` for grouped headers and block
  content inside header cells;
* ``paperlyft_reporting_period_summary.html`` for multiple tables;
* ``paperlyft_income_expense_ledger.html``; and
* ``paperlyft_real_property_disclosure.html``.

Run the focused coverage with:

.. code-block:: sh

   pytest tests/test_pdf.py -k "table_header or paperlyft_table"

Any future table-tagging change must keep visual rendering stable and validate
the emitted PDF structure independently. A visual match alone is insufficient:
the published 69.0 output looked identical while its table structure failed
PDF/UA-1.
