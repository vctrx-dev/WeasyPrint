"""PDF tagging."""

from collections import defaultdict

import pydyf

from ..formatting_structure import boxes
from ..html import SPACE_SEPARATED_TOKENS_RE
from ..layout.absolute import AbsolutePlaceholder
from ..logger import LOGGER


def _resolve_table_headers(
        headers_attribute, current_header_ids, persisted_header_ids,
        principal_header_id=None):
    """Return valid PDF header IDs and whether a header is not known yet."""
    headers = []
    unresolved = False
    seen_header_ids = set()
    for source_id in SPACE_SEPARATED_TOKENS_RE.findall(headers_attribute):
        if source_id in seen_header_ids:
            continue
        seen_header_ids.add(source_id)
        header_id = current_header_ids.get(source_id)
        if header_id is None:
            header_id = persisted_header_ids.get(source_id)
        if header_id is None:
            unresolved = True
        elif header_id != principal_header_id:
            headers.append(header_id)
    return pydyf.Array(headers), unresolved


def _get_link_annotations(box, tags):
    """Return the link annotations generated for this page's tag stream."""
    link_annotations = getattr(box, 'link_annotations', None)
    if link_annotations is not None:
        return link_annotations.pop(tags.annotation_token, ())
    return (box.link_annotation,) if box.link_annotation else ()


def _add_marked_content(element, kid, page_number, nums, form_nums, pdf):
    """Add a marked-content kid and its ParentTree mapping."""
    stream = kid['stream']
    if stream.extra.get('Subtype') == '/Form':
        stream_nums = form_nums.setdefault(stream, {})
        assert kid['mcid'] not in stream_nums
        stream_nums[kid['mcid']] = element.reference
        return pydyf.Dictionary({
            'Type': '/MCR',
            'MCID': kid['mcid'],
            'Pg': pdf.page_references[page_number],
            'Stm': stream.reference,
        })

    assert kid['mcid'] not in nums
    nums[kid['mcid']] = element.reference
    return kid['mcid']


def _set_table_row_indices(table_element, row_indices):
    """Set logical row indices from the source table's row-group order."""
    if row_indices or table_element is None:
        return

    header_groups = []
    body_groups = []
    footer_groups = []
    seen_header = seen_footer = False
    for child in table_element:
        tag = child.tag.rsplit('}', 1)[-1] if isinstance(child.tag, str) else ''
        if tag == 'tr':
            body_groups.append((child,))
        elif tag in ('thead', 'tbody', 'tfoot'):
            rows = tuple(
                row for row in child
                if isinstance(row.tag, str) and
                row.tag.rsplit('}', 1)[-1] == 'tr')
            if tag == 'thead' and not seen_header:
                header_groups.append(rows)
                seen_header = True
            elif tag == 'tfoot' and not seen_footer:
                footer_groups.append(rows)
                seen_footer = True
            else:
                body_groups.append(rows)

    for rows in (*header_groups, *body_groups, *footer_groups):
        for row in rows:
            row_indices.setdefault(id(row), len(row_indices))


def add_tags(pdf, document, pdf_version, page_streams):
    """Add tag tree to the document."""

    # Add root structure.
    content_mapping = pydyf.Dictionary({})
    pdf.add_object(content_mapping)
    structure_root = pydyf.Dictionary({
        'Type': '/StructTreeRoot',
        'ParentTree': content_mapping.reference,
    })
    pdf.add_object(structure_root)
    structure_document = pydyf.Dictionary({
        'Type': '/StructElem',
        'S': '/Document',
        'K': pydyf.Array(),
        'P': structure_root.reference,
    })
    pdf.add_object(structure_document)
    structure_root['K'] = pydyf.Array([structure_document.reference])
    pdf.catalog['StructTreeRoot'] = structure_root.reference

    # Add namespace for PDF 2.
    if str(pdf_version) >= '2.0':  # Cast for bytes and None
        namespace = pydyf.Dictionary({
            'Type': '/Namespace',
            'NS': pydyf.String('http://iso.org/pdf2/ssn'),
        })
        pdf.add_object(namespace)
        structure_root['Namespaces'] = pydyf.Array([namespace.reference])
        structure_document['NS'] = namespace.reference

    # Map content.
    content_mapping['Nums'] = pydyf.Array()
    annotations = []
    form_nums = {}
    table_header_ids = defaultdict(dict)
    table_content_header_ids = defaultdict(dict)
    table_row_headers = defaultdict(lambda: defaultdict(dict))
    table_column_headers = defaultdict(lambda: defaultdict(dict))
    table_column_group_headers = defaultdict(lambda: defaultdict(dict))
    table_row_group_headers = defaultdict(lambda: defaultdict(dict))
    table_row_indices = defaultdict(dict)
    pending_table_headers = defaultdict(list)
    table_annotation_elements = {}
    table_structure_elements = {}
    table_header_elements = {}
    figure_elements = {}
    pending_figure_captions = defaultdict(list)
    fragmented_table_elements = set()
    for page in document.pages:
        for box in page._page_box.descendants(placeholders=True):
            if (isinstance(box, boxes.TableBox) and
                    box.is_fragmented_table and box.element is not None):
                fragmented_table_elements.add(id(box.element))
    for page_number, (page, stream) in enumerate(zip(document.pages, page_streams)):
        tags = stream._tags
        page_box = page._page_box

        # Prepare array for this page’s MCID-to-StructElem mapping.
        content_mapping['Nums'].append(page_number)
        content_mapping['Nums'].append(pydyf.Array())
        page_nums = {}

        # Map page box content.
        elements = _build_box_tree(
            page_box, structure_document, pdf, page_number, page_nums, form_nums,
            annotations,
            tags, table_header_ids, table_content_header_ids,
            table_row_headers,
            table_column_headers,
            table_column_group_headers,
            table_row_group_headers, table_row_indices,
            pending_table_headers, table_annotation_elements,
            table_structure_elements, table_header_elements,
            fragmented_table_elements, figure_elements, pending_figure_captions)
        for element in elements:
            structure_document['K'].append(element.reference)
        assert not tags

        # Flatten page-local nums into global mapping.
        sorted_refs = [ref for _, ref in sorted(page_nums.items())]
        content_mapping['Nums'][-1].extend(sorted_refs)

    next_struct_parent = len(document.pages)
    for stream, nums in form_nums.items():
        stream.extra['StructParents'] = next_struct_parent
        content_mapping['Nums'].append(next_struct_parent)
        content_mapping['Nums'].append(pydyf.Array(
            reference for _, reference in sorted(nums.items())))
        next_struct_parent += 1

    # Resolve explicit references to headers first tagged on a later page.
    for table_id, pending_headers in pending_table_headers.items():
        persisted_header_ids = table_header_ids[table_id]
        for (attributes, headers_attribute, current_header_ids,
             principal_header_id) in pending_headers:
            attributes['Headers'], _ = _resolve_table_headers(
                headers_attribute, current_header_ids, persisted_header_ids,
                principal_header_id)

    if table_header_elements:
        id_tree = pydyf.Dictionary({'Names': pydyf.Array()})
        for header_id, element in sorted(table_header_elements.items()):
            id_tree['Names'].append(pydyf.String(header_id))
            id_tree['Names'].append(element.reference)
        pdf.add_object(id_tree)
        structure_root['IDTree'] = id_tree.reference

    # Add annotations for links and widgets.
    start = next_struct_parent
    for i, (reference, annotation) in enumerate(annotations, start=start):
        content_mapping['Nums'].append(i)
        content_mapping['Nums'].append(reference)
        annotation['StructParent'] = i

    # Add required metadata.
    pdf.catalog['ViewerPreferences'] = pydyf.Dictionary({'DisplayDocTitle': 'true'})
    pdf.catalog['MarkInfo'] = pydyf.Dictionary({'Marked': 'true'})
    if 'Lang' not in pdf.catalog:
        LOGGER.error('Missing required "lang" attribute at the root of the document')
        pdf.catalog['Lang'] = pydyf.String()


def _get_pdf_tag(tag):
    """Get PDF tag corresponding to HTML tag."""
    if tag is None:
        return 'NonStruct'
    elif tag == 'div':
        return 'Div'
    elif tag.split(':')[0] == 'a':
        # Links and link pseudo elements create link annotations.
        return 'Link'
    elif tag == 'span':
        return 'Span'
    elif tag == 'main':
        return 'Part'
    elif tag == 'article':
        return 'Art'
    elif tag == 'section':
        return 'Sect'
    elif tag == 'blockquote':
        return 'BlockQuote'
    elif tag == 'p':
        return 'P'
    elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        return tag.upper()
    elif tag in ('dl', 'ul', 'ol'):
        return 'L'
    elif tag in ('li', 'dt', 'dd'):
        # TODO: dt should be different.
        return 'LI'
    elif tag == 'li::marker':
        return 'Lbl'
    elif tag == 'table':
        return 'Table'
    elif tag in ('tr', 'th', 'td'):
        return tag.upper()
    elif tag in ('thead', 'tbody', 'tfoot'):
        return tag[:2].upper() + tag[2:]
    elif tag == 'img' or tag == '{http://www.w3.org/2000/svg}svg':
        return 'Figure'
    elif tag in ('caption', 'figcaption'):
        return 'Caption'
    else:
        return 'NonStruct'


def _add_annotation(element, annotation, pdf, page_number, annotations):
    """Add an annotation object reference to a structure element."""
    object_reference = pydyf.Dictionary({
        'Type': '/OBJR',
        'Obj': annotation.reference,
        'Pg': pdf.page_references[page_number],
    })
    pdf.add_object(object_reference)
    annotations.append((element.reference, annotation))
    element['K'].append(object_reference.reference)


def _add_widget_annotation(parent, annotation, pdf, page_number, annotations):
    """Add a one-widget Form structure element below ``parent``."""
    form_element = pydyf.Dictionary({
        'Type': '/StructElem',
        'S': '/Form',
        'K': pydyf.Array(),
        'Pg': pdf.page_references[page_number],
        'P': parent.reference,
    })
    pdf.add_object(form_element)
    _add_annotation(form_element, annotation, pdf, page_number, annotations)
    parent['K'].append(form_element.reference)


def _table_child_insert_index(
        parent, children, table_structure_elements, table_context, index):
    """Keep newly seen table groups in source order across page fragments."""
    group_order = {'THead': 0, 'TBody': 1, 'TFoot': 2}
    if parent['S'] != '/Table' or len(children) != 1:
        return index
    child_tag = str(children[0]['S'])[1:]
    child_order = group_order.get(child_tag)
    if child_order is None:
        return index
    element_tags = {
        element.reference: tag
        for (context, tag, _), element in table_structure_elements.items()
        if context == table_context}
    for index, reference in enumerate(parent['K']):
        if group_order.get(element_tags.get(reference), -1) > child_order:
            return index
    return len(parent['K'])


def _build_box_tree(
        box, parent, pdf, page_number, nums, form_nums, annotations, tags,
        table_header_ids, table_content_header_ids, table_row_headers,
        table_column_headers,
        table_column_group_headers,
        table_row_group_headers, table_row_indices, pending_table_headers,
        table_annotation_elements, table_structure_elements,
        table_header_elements, fragmented_table_elements, figure_elements,
        pending_figure_captions, table_context=None, figure_context=None):
    """Recursively build tag tree for given box and yield children."""

    # Special case for absolute elements.
    if isinstance(box, AbsolutePlaceholder):
        box = box._box

    if box.is_decorative_image:
        return

    if box.is_repeated_table_header:
        seen_annotations = set()
        for header_box in box.descendants(placeholders=True):
            annotation_sets = (
                ('Link', _get_link_annotations(header_box, tags)),
                ('Form', (header_box.widget_annotation,)
                 if header_box.widget_annotation else ()))
            for annotation_tag, page_annotations in annotation_sets:
                for annotation in page_annotations:
                    if annotation.reference in seen_annotations:
                        continue
                    seen_annotations.add(annotation.reference)
                    element = table_annotation_elements.get(
                        (annotation_tag, id(header_box.element)))
                    assert element is not None
                    if annotation_tag == 'Form':
                        _add_widget_annotation(
                            element, annotation, pdf, page_number, annotations)
                    else:
                        _add_annotation(
                            element, annotation, pdf, page_number, annotations)
        return

    element_tag = None if box.element is None else box.element_tag
    tag = _get_pdf_tag(element_tag)
    if element_tag == 'figure':
        figure_context = id(box.element)
    if tag == 'Table':
        table_box = box.get_wrapped_table() if box.is_table_wrapper else box
        table_element = (
            table_box.element if table_box is not None else box.element)
        if (table_element is not None and
                id(table_element) in fragmented_table_elements):
            table_context = id(table_element)

    # Handle special cases.
    if element_tag in ('html', 'body') or isinstance(box, boxes.PageBox):
        # Avoid generate page, html and body boxes as a semantic node, yield children.
        if isinstance(box, boxes.ParentBox) and not isinstance(box, boxes.LineBox):
            for child in box.children:
                yield from _build_box_tree(
                    child, parent, pdf, page_number, nums, form_nums,
                    annotations, tags,
                    table_header_ids, table_content_header_ids,
                    table_row_headers,
                    table_column_headers,
                    table_column_group_headers,
                    table_row_group_headers, table_row_indices,
                    pending_table_headers, table_annotation_elements,
                    table_structure_elements, table_header_elements,
                    fragmented_table_elements, figure_elements,
                    pending_figure_captions, table_context, figure_context)
            return
    elif isinstance(box, boxes.MarginBox):
        # Build tree for margin boxes but don’t link it to main tree. It ensures that
        # marked content is mapped in document and removed from list. It could be
        # included in tree as Artifact, but that’s only allowed in PDF 2.0.
        for child in box.children:
            tuple(_build_box_tree(
                child, parent, pdf, page_number, nums, form_nums,
                annotations, tags,
                table_header_ids, table_content_header_ids,
                table_row_headers,
                table_column_headers,
                table_column_group_headers,
                table_row_group_headers, table_row_indices,
                pending_table_headers, table_annotation_elements,
                table_structure_elements, table_header_elements,
                fragmented_table_elements, figure_elements,
                pending_figure_captions, table_context, figure_context))
        return
    elif tag in ('TD', 'TH'):
        # Ignore anonymous blocks created for table cells.
        if parent['S'] in ('/TD', '/TH'):
            tag = 'NonStruct'
    elif tag == 'LI':
        # Ignore anonymous blocks created for lists and bullets.
        anonymous_list_element = parent['S'] == '/LI'
        anonymous_li_child = parent['S'] == '/LBody'
        dl_item = box.element_tag in ('dt', 'dd')
        no_bullet_li = box.element_tag == 'li' and (
            'list-item' not in box.style['display'] or
            box.style['list_style_type'] == 'none')
        if anonymous_list_element:
            # Store as list item body.
            tag = 'LBody'
        elif anonymous_li_child:
            # Store as non struct list item body child.
            tag = 'NonStruct'
        elif dl_item or no_bullet_li:
            # Wrap in list item.
            tag = 'LBody'
            parent = pydyf.Dictionary({
                'Type': '/StructElem',
                'S': '/LI',
                'K': pydyf.Array([]),
                'Pg': pdf.page_references[page_number],
                'P': parent.reference,
            })
            pdf.add_object(parent)
            children = _build_box_tree(
                box, parent, pdf, page_number, nums, form_nums,
                annotations, tags,
                table_header_ids, table_content_header_ids,
                table_row_headers,
                table_column_headers,
                table_column_group_headers,
                table_row_group_headers, table_row_indices,
                pending_table_headers, table_annotation_elements,
                table_structure_elements, table_header_elements,
                fragmented_table_elements, figure_elements,
                pending_figure_captions, table_context, figure_context)
            for child in children:
                parent['K'].append(child.reference)
            yield parent
            return

    # Reuse source table elements across physical page fragments, keeping one
    # logical table tree while their page-local content stays in the ParentTree.
    table_structure_key = None
    table_source_box = (
        (tag == 'Table' and (
            box.is_table_wrapper or isinstance(box, boxes.TableBox))) or
            (tag in ('THead', 'TBody', 'TFoot') and
                isinstance(box, boxes.TableRowGroupBox)) or
            (tag == 'TR' and isinstance(box, boxes.TableRowBox)) or
            (tag in ('TH', 'TD') and isinstance(box, boxes.TableCellBox)) or
            (tag == 'Caption' and isinstance(box, boxes.TableCaptionBox)))
    if table_context is not None and table_source_box and box.element is not None:
        table_structure_key = (table_context, tag, id(box.element))
    element = table_structure_elements.get(table_structure_key)
    new_element = element is None
    if new_element:
        element = pydyf.Dictionary({
            'Type': '/StructElem',
            'S': f'/{tag}',
            'K': pydyf.Array([]),
            'Pg': pdf.page_references[page_number],
            'P': parent.reference,
        })
        pdf.add_object(element)
        if table_structure_key is not None:
            table_structure_elements[table_structure_key] = element

    if (tag == 'Figure' and figure_context is not None and
            isinstance(box, boxes.ReplacedBox)):
        if figure_context not in figure_elements:
            figure_elements[figure_context] = element
            for caption, caption_parent in pending_figure_captions.pop(
                    figure_context, ()):
                caption_parent['K'].remove(caption.reference)
                caption['P'] = element.reference
                element['K'].append(caption.reference)

    # Handle special cases.
    if tag == 'Figure':
        # Add extra data for images.
        x1, y1 = box.content_box_x(), box.content_box_y()
        x2, y2 = x1 + box.width, y1 + box.height
        element['A'] = pydyf.Dictionary({
            'O': '/Layout',
            'BBox': pydyf.Array((x1, y1, x2, y2)),
        })
        # Add alternate text for images/figures.
        # If it's an SVG element, we look for the <title> element inside.
        # Otherwise, we revert to the "alt" attribute if its not an SVG.
        if box.element.tag == '{http://www.w3.org/2000/svg}svg':
            title_elem = box.element.find('{http://www.w3.org/2000/svg}title')
            if title_elem is not None and title_elem.text:
                element['Alt'] = pydyf.String(title_elem.text)
            else:
                desc_elem = box.element.find('{http://www.w3.org/2000/svg}desc')
                if desc_elem is not None and desc_elem.text:
                    element['Alt'] = pydyf.String(desc_elem.text)
        elif alt := box.element.attrib.get('alt'):
            element['Alt'] = pydyf.String(alt)
        else:
            source = box.element.attrib.get('src', 'unknown')
            LOGGER.error('Image "%s" has no required alt description', source)
    elif tag == 'Table':
        # Use wrapped table as tagged box, and put captions in it.
        if box.is_table_wrapper:
            # Can be false if table has another display type.
            wrapper, table = box, box.get_wrapped_table()
            if table:
                box = table.copy_with_children([])
                for child in wrapper.children:
                    box.children.extend(child.children if child is table else [child])
    elif tag in ('TH', 'TD'):
        if 'A' not in element:
            element['A'] = pydyf.Dictionary({'O': '/Table'})
        attributes = element['A']
        # PDF/UA derives effective table geometry from structure attributes,
        # not painted borders. Keep layout spans on the semantic cell.
        if box.colspan != 1:
            attributes['ColSpan'] = box.colspan
        if box.rowspan != 1:
            attributes['RowSpan'] = box.rowspan
        if tag == 'TH':
            # PDF/UA-1 has direct row and column scopes only. Grouped HTML
            # scopes are expanded into concrete Headers associations below.
            scope = box.element.attrib.get('scope', '').lower()
            if scope == 'row':
                attributes['Scope'] = '/Row'
            elif scope == 'col':
                attributes['Scope'] = '/Column'
        # Store table cell element to map headers to cells later.
        # TODO: don’t use the box to store this.
        box.mark = element
        box.mark_content_length = len(element['K'])

    # Include link annotations.
    for annotation in _get_link_annotations(box, tags):
        table_annotation_elements.setdefault(
            ('Link', id(box.element)), element)
        _add_annotation(element, annotation, pdf, page_number, annotations)

    # Include widget annotations.
    if box.widget_annotation:
        annotation = box.widget_annotation
        table_annotation_elements.setdefault(
            ('Form', id(box.element)), element)
        _add_widget_annotation(
            element, annotation, pdf, page_number, annotations)

    # Build tree for box children.
    for child in box.children:
        children = child.children if isinstance(child, boxes.LineBox) else [child]
        for child in children:
            if isinstance(child, boxes.TextBox):
                # Add marked element from the stream.
                kid = tags.pop(child)
                if tag == 'Link':
                    # Associate MCID directly with link reference.
                    element['K'].append(_add_marked_content(
                        element, kid, page_number, nums, form_nums, pdf))
                else:
                    kid_element = pydyf.Dictionary({
                        'Type': '/StructElem',
                        'S': f'/{kid["tag"]}',
                        'K': pydyf.Array(),
                        'Pg': pdf.page_references[page_number],
                        'P': element.reference,
                    })
                    pdf.add_object(kid_element)
                    kid_element['K'].append(_add_marked_content(
                        kid_element, kid, page_number, nums, form_nums, pdf))
                    element['K'].append(kid_element.reference)
            else:
                # Recursively build tree for child.
                if child.element_tag in ('ul', 'ol') and element['S'] == '/LI':
                    # In PDFs, nested lists are linked to the parent list, but in
                    # HTML, nested lists are linked to a parent’s list item.
                    child_parent = parent
                elif child.element_tag == 'figcaption':
                    child_parent = figure_elements.get(figure_context, element)
                else:
                    child_parent = element
                # Keep the current number of parent children, so that we can add the
                # new children before the possible grandchildren, for example for
                # lists.
                child_index = len(child_parent['K'])
                child_elements = tuple(_build_box_tree(
                    child, child_parent, pdf, page_number, nums, form_nums,
                    annotations, tags,
                    table_header_ids, table_content_header_ids,
                    table_row_headers,
                    table_column_headers,
                    table_column_group_headers,
                    table_row_group_headers, table_row_indices,
                    pending_table_headers, table_annotation_elements,
                    table_structure_elements, table_header_elements,
                    fragmented_table_elements, figure_elements,
                    pending_figure_captions, table_context, figure_context))
                child_index = _table_child_insert_index(
                    child_parent, child_elements, table_structure_elements,
                    table_context, child_index)
                child_parent['K'][child_index:child_index] = [
                    element.reference for element in child_elements]
                if (child.element_tag == 'figcaption' and
                        figure_context is not None and
                        figure_context not in figure_elements):
                    pending_figure_captions[figure_context].extend(
                        (child_element, child_parent)
                        for child_element in child_elements
                        if child_element['S'] == '/Caption')

    if isinstance(box, boxes.ReplacedBox):
        # Add replaced box.
        kid = tags.pop(box)
        element['K'].append(_add_marked_content(
            element, kid, page_number, nums, form_nums, pdf))

    # Link table cells to related headers.
    if tag == 'Table':
        def _get_rows(table_box, row_group=None):
            for child in table_box.children:
                if child.is_repeated_table_header:
                    continue
                if child.element_tag == 'tr':
                    yield child, row_group
                else:
                    child_row_group = (
                        child if isinstance(child, boxes.TableRowGroupBox)
                        else row_group)
                    yield from _get_rows(child, child_row_group)

        # Get headers and rows.
        column_headers = defaultdict(dict)
        row_headers = defaultdict(dict)
        row_group_headers = defaultdict(dict)
        column_group_headers = defaultdict(dict)
        table_id = id(box.element)
        persisted_header_ids = table_header_ids[table_id]
        content_header_ids = table_content_header_ids[table_id]
        persisted_row_headers = table_row_headers[table_id]
        persisted_column_headers = table_column_headers[table_id]
        persisted_column_group_headers = table_column_group_headers[table_id]
        persisted_row_group_headers = table_row_group_headers[table_id]
        row_indices = table_row_indices[table_id]
        current_header_ids = {}
        _set_table_row_indices(box.element, row_indices)
        rows = tuple(_get_rows(box))

        def _get_column_group(column):
            for column_group in getattr(box, 'column_groups', ()):
                if (column_group.element is not None and
                        column_group.grid_x <= column <
                        column_group.grid_x + column_group.span):
                    return column_group

        def _get_row_group_key(row_group):
            if row_group is not None and row_group.element is not None:
                return id(row_group.element)

        def _get_row_index(row):
            row_key = id(row.element) if row.element is not None else id(row)
            return row_indices.setdefault(row_key, len(row_indices))

        # Find column and row headers.
        for local_i, (row, row_group) in enumerate(rows):
            i = _get_row_index(row)
            for cell in row.children:
                j = cell.grid_x
                if cell.element is not None and cell.element_tag == 'th':
                    row_id = i if table_context is not None else local_i
                    physical_key = pydyf.String(
                        f'{element.number}-{row_id}-{j}')
                    if key := content_header_ids.get(id(cell.element)):
                        # Keep split header cells attached to their source ID.
                        pass
                    else:
                        key = physical_key
                        content_header_ids[id(cell.element)] = key
                        cell.mark['ID'] = key
                        table_header_elements[key.string] = cell.mark
                    if source_id := cell.element.attrib.get('id'):
                        current_header_ids.setdefault(source_id, key)
                        persisted_header_ids.setdefault(source_id, key)
                    scope = cell.element.attrib.get('scope', '').lower()
                    if scope == 'row':
                        header = (key, j, cell.colspan)
                        for row_index in range(i, i + cell.rowspan):
                            row_headers[row_index][id(cell.element)] = header
                            persisted_row_headers[row_index].setdefault(
                                id(cell.element), header)
                    elif scope == 'rowgroup':
                        if row_group_key := _get_row_group_key(row_group):
                            header = (key, i, j)
                            row_group_headers[row_group_key][id(cell.element)] = header
                            persisted_row_group_headers[row_group_key].setdefault(
                                id(cell.element), header)
                    elif scope == 'colgroup':
                        if column_group := _get_column_group(j):
                            column_group_key = id(column_group.element)
                            header = (key, i, j)
                            column_group_headers[column_group_key][
                                id(cell.element)] = header
                            persisted_column_group_headers[
                                column_group_key].setdefault(
                                    id(cell.element), header)
                    else:
                        for column in range(j, j + cell.colspan):
                            header = (key, i, cell.rowspan)
                            column_headers[column][id(cell.element)] = header
                            persisted_column_headers[column].setdefault(
                                id(cell.element), header)

        # Map headers to cells.
        for row, row_group in rows:
            i = _get_row_index(row)
            for cell in row.children:
                j = cell.grid_x
                headers_attribute = (
                    cell.element.attrib.get('headers')
                    if cell.element is not None and
                    cell.element_tag in ('th', 'td') else None)
                if headers_attribute is not None:
                    principal_header_id = (
                        cell.mark['ID'] if 'ID' in cell.mark else None)
                    if (principal_header_id is None and
                            cell.element_tag == 'th'):
                        principal_header_id = content_header_ids.get(
                            id(cell.element))
                    headers, unresolved = _resolve_table_headers(
                        headers_attribute, current_header_ids,
                        persisted_header_ids, principal_header_id)
                    cell.mark['A']['Headers'] = headers
                    if unresolved:
                        pending_table_headers[id(box.element)].append((
                            cell.mark['A'], headers_attribute,
                            current_header_ids.copy(), principal_header_id))
                elif cell.element is not None and cell.element_tag == 'td':
                    headers = []
                    for span in range(cell.rowspan):
                        headers_for_row = dict(
                            persisted_row_headers[i + span])
                        headers_for_row.update(row_headers[i + span])
                        headers += [
                            header for header, header_j, header_colspan
                            in headers_for_row.values()
                            if header_j + header_colspan <= j]
                    for span in range(cell.colspan):
                        headers_for_column = dict(
                            persisted_column_headers[j + span])
                        headers_for_column.update(column_headers[j + span])
                        headers += [
                            header for header, header_i, header_rowspan
                            in headers_for_column.values()
                            if header_i + header_rowspan <= i]
                    if row_group_key := _get_row_group_key(row_group):
                        group_headers = dict(
                            persisted_row_group_headers[row_group_key])
                        group_headers.update(row_group_headers[row_group_key])
                        headers += [
                            header for header, header_i, header_j
                            in group_headers.values()
                            if header_i <= i + cell.rowspan - 1 and
                            header_j <= j + cell.colspan - 1]
                    for span in range(cell.colspan):
                        if column_group := _get_column_group(j + span):
                            column_group_key = id(column_group.element)
                            group_headers = dict(
                                persisted_column_group_headers[
                                    column_group_key])
                            group_headers.update(
                                column_group_headers[column_group_key])
                            headers += [
                                header for header, header_i, header_j
                                in group_headers.values()
                                if header_i <= i + cell.rowspan - 1 and
                                header_j <= j + cell.colspan - 1]
                    headers = list(dict.fromkeys(headers))
                    cell.mark['A']['Headers'] = pydyf.Array(headers)

    if new_element:
        yield element
