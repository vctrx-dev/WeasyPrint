"""Stacking contexts management."""

from .formatting_structure import boxes
from .layout.absolute import AbsolutePlaceholder


class StackingContext:
    """Stacking contexts define the paint order of all pieces of a document.

    https://www.w3.org/TR/CSS21/visuren.html#x43
    https://www.w3.org/TR/CSS21/zindex.html

    """
    def __init__(self, box, child_contexts, blocks, floats, blocks_and_cells,
                 page):
        self.box = box
        self.page = page
        self.block_level_boxes = blocks  # 4: In flow, non positioned
        self.float_contexts = floats  # 5: Non positioned
        self.negative_z_contexts = []  # 3: Child contexts, z-index < 0
        self.zero_z_contexts = []  # 8: Child contexts, z-index = 0
        self.positive_z_contexts = []  # 9: Child contexts, z-index > 0
        self.blocks_and_cells = blocks_and_cells  # 7: Non positioned

        for context in child_contexts:
            if context.z_index < 0:
                self.negative_z_contexts.append(context)
            elif context.z_index == 0:
                self.zero_z_contexts.append(context)
            else:  # context.z_index > 0
                self.positive_z_contexts.append(context)
        self.negative_z_contexts.sort(key=lambda context: context.z_index)
        self.positive_z_contexts.sort(key=lambda context: context.z_index)
        # sort() is stable, so the lists are now storted
        # by z-index, then tree order.

        self.z_index = box.style['z_index']
        if self.z_index == 'auto':
            self.z_index = 0

    @classmethod
    def from_page(cls, page):
        # Page children (the box for the root element and margin boxes)
        # as well as the page box itself are unconditionally stacking contexts.
        child_contexts = [cls.from_box(child, page) for child in page.children]
        # Children are sub-contexts, remove them from the "normal" tree.
        page = page.copy_with_children([])
        return cls(page, child_contexts, [], [], {}, page)

    @classmethod
    def from_box(cls, box, page, child_contexts=None):
        children = []  # What will be passed to this box
        if child_contexts is None:
            child_contexts = children
        # child_contexts: where to put sub-contexts that we find here.
        # May not be the same as children for:
        #   "treat the element as if it created a new stacking context, but any
        #    positioned descendants and descendants which actually create a new
        #    stacking context should be considered part of the parent stacking
        #    context, not this new one."
        blocks = []
        floats = []
        blocks_and_cells = {}
        box = _dispatch_children(
            box, page, child_contexts, blocks, floats, blocks_and_cells)
        return cls(box, children, blocks, floats, blocks_and_cells, page)


def _dispatch(box, page, child_contexts, blocks, floats, blocks_and_cells):
    if isinstance(box, AbsolutePlaceholder):
        box = box._box
    style = box.style

    # Remove boxes defining a new stacking context from the children list.
    # A clipped box is drawn as a sub-context so that the clip wraps its whole
    # subtree. Replaced boxes have no subtree, and the UA stylesheet clips every
    # image, so making them sub-contexts only delays their paint until after all
    # in-flow content. That delay becomes the marked-content order of the page,
    # which puts every image last in the tagged reading order tools display.
    # `draw_replacedbox` applies their clip instead.
    clipped = (
        style['overflow'] != 'visible' and
        not isinstance(box, boxes.ReplacedBox))
    defines_stacking_context = (
        (style['position'] != 'static' and style['z_index'] != 'auto') or
        (box.is_grid_item and style['z_index'] != 'auto') or
        style['opacity'] < 1 or
        style['transform'] or  # 'transform: none' gives a "falsy" empty list
        clipped)
    if defines_stacking_context:
        child_contexts.append(StackingContext.from_box(box, page))
        return

    stacking_classes = (boxes.InlineBlockBox, boxes.InlineFlexBox, boxes.InlineGridBox)
    if style['position'] != 'static':
        assert style['z_index'] == 'auto'
        # "Fake" context: sub-contexts will go in this `child_contexts` list.
        # Insert at the position before creating the sub-context.
        index = len(child_contexts)
        stacking_context = StackingContext.from_box(box, page, child_contexts)
        child_contexts.insert(index, stacking_context)
    elif box.is_floated():
        floats.append(StackingContext.from_box(box, page, child_contexts))
    elif isinstance(box, stacking_classes):
        # Have this fake stacking context be part of the "normal" box tree,
        # because we need its position in the middle of a tree of inline boxes.
        return StackingContext.from_box(box, page, child_contexts)
    else:
        if isinstance(box, boxes.BlockLevelBox):
            blocks_index = len(blocks)
            box_blocks_and_cells = {}
            box = _dispatch_children(
                box, page, child_contexts, blocks, floats, box_blocks_and_cells)
            blocks.insert(blocks_index, box)
            blocks_and_cells[box] = box_blocks_and_cells
        elif isinstance(box, boxes.TableCellBox):
            box_blocks_and_cells = {}
            box = _dispatch_children(
                box, page, child_contexts, blocks, floats, box_blocks_and_cells)
            blocks_and_cells[box] = box_blocks_and_cells
        else:
            blocks_index = None
            box_blocks_and_cells = None
            box = _dispatch_children(
                box, page, child_contexts, blocks, floats, blocks_and_cells)

        return box


def _dispatch_children(box, page, child_contexts, blocks, floats,
                       blocks_and_cells):
    if not isinstance(box, boxes.ParentBox):
        return box

    if box.element_tag == 'input':
        # Associate generated appearance with this laid-out control before
        # dispatch separates positioned/opacity descendants from their parent.
        for descendant in box.descendants():
            if (descendant.element is box.element and
                    descendant.element_tag in ('input::before', 'input::after')):
                descendant.static_control_owner = box

    new_children = []
    for child in box.children:
        result = _dispatch(
            child, page, child_contexts, blocks, floats, blocks_and_cells)
        if result is not None:
            new_children.append(result)
    copy = box.copy_with_children(new_children)
    if box.element_tag == 'input':
        # Paint copies must refer to this layout instance, not to the HTML
        # element shared by independent running and paginated copies.
        copy.static_control_owner = box
    return copy
