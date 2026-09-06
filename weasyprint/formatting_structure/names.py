"""Native control names resolved before layout fragments the document."""

from collections import defaultdict

from .. import html


def get_static_control_names(root, style_for):
    """Resolve HTML labels and textual ARIA names, not the full AccName algorithm.

    CSS-generated content and embedded control values are not resolved here.
    Never infer a name from nearby text, a submission name, or a checkbox value.
    """
    elements = tuple(root.iter())
    ids = {}
    parents = {child: parent for parent in elements for child in parent}
    for element in elements:
        if element_id := element.get('id'):
            ids.setdefault(element_id, element)

    def labelable(element):
        return element is not None and (
            element.tag in ('button', 'meter', 'output', 'progress',
                            'select', 'textarea') or
            (element.tag == 'input' and element.get('type', '').lower() != 'hidden'))

    def aria_hidden(element):
        if element.get('aria-hidden') == 'true':
            return True
        parent = parents.get(element)
        return parent is not None and aria_hidden(parent)

    def hidden_subtree(element):
        style = style_for(element)
        if (element.get('aria-hidden') == 'true' or style is None or
                style['display'] == ('none',)):
            return True
        parent = parents.get(element)
        return parent is not None and hidden_subtree(parent)

    def hidden(element):
        return (hidden_subtree(element) or
                style_for(element)['visibility'] != 'visible')

    def text(element, include_hidden=False):
        if not isinstance(element.tag, str) or (
                not include_hidden and hidden_subtree(element)):
            return ''
        visible = include_hidden or style_for(element)['visibility'] == 'visible'
        if visible and (name := element.get('aria-label', '').strip()):
            return name
        if element.tag == 'img':
            return element.get('alt', '') if visible else ''
        if element.tag == 'br':
            return ' '
        if element.tag == 'input':
            return ''
        result = (element.text or '') if visible else ''
        for child in element:
            child_text = text(child, include_hidden)
            style = style_for(child) if isinstance(child.tag, str) else None
            if style is not None and style['display'][0] not in ('inline', 'none'):
                child_text = f' {child_text} '
            result += child_text + ((child.tail or '') if visible else '')
        return result

    labels = defaultdict(list)
    for label in elements:
        if label.tag != 'label':
            continue
        if 'for' in label.attrib:
            control = ids.get(label.get('for'))
        else:
            control = next((child for child in label.iter()
                            if labelable(child)), None)
        if labelable(control):
            labels[control].append(label)

    names = {}
    for element in elements:
        if (element.tag != 'input' or
                element.get('type', '').lower() not in ('checkbox', 'radio') or
                aria_hidden(element)):
            continue
        references = [ids[token] for token in dict.fromkeys(
            html.SPACE_SEPARATED_TOKENS_RE.findall(element.get('aria-labelledby', '')))
            if token in ids]
        if references:
            # An explicitly referenced hidden subtree still supplies a name.
            name = ' '.join(text(reference, hidden(reference))
                            for reference in references)
        elif name := element.get('aria-label', '').strip():
            pass
        elif element in labels:
            name = ' '.join(text(label, hidden(label)) for label in labels[element])
        else:
            name = element.get('title', '')
        names[element] = ' '.join(name.split())
    return names
