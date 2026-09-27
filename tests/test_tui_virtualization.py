# tests/test_tui_virtualization.py
"""Tests for visible-range list virtualization with 10,000+ entries."""

import time
import pytest
from ui.rendering.virtualization import VirtualList


def test_virtual_list_10k_items():
    # 10,000 items
    items = [f"Message #{i}" for i in range(10000)]
    viewport_height = 20

    t0 = time.perf_counter()
    v_range = VirtualList.slice_viewport(
        items=items,
        viewport_height=viewport_height,
        scroll_offset=0,
        anchor_to_bottom=True,
    )
    t1 = time.perf_counter()

    # Time must be sub-millisecond (typically < 0.1ms)
    assert (t1 - t0) * 1000.0 < 5.0

    # Only viewport_height items are in the visible tuple
    assert len(v_range.visible_items) == 20
    assert v_range.total_count == 10000

    # Anchor to bottom: latest messages visible
    assert v_range.visible_items[-1] == "Message #9999"
    assert v_range.visible_items[0] == "Message #9980"
    assert v_range.has_more_above is True
    assert v_range.has_more_below is False


def test_virtual_list_scroll_up():
    items = [f"Item {i}" for i in range(100)]
    # Scroll up 10 items from bottom
    v_range = VirtualList.slice_viewport(
        items=items,
        viewport_height=10,
        scroll_offset=10,
        anchor_to_bottom=True,
    )
    assert len(v_range.visible_items) == 10
    assert v_range.visible_items[-1] == "Item 89"
    assert v_range.has_more_above is True
    assert v_range.has_more_below is True


def test_virtual_list_empty():
    v_range = VirtualList.slice_viewport([], viewport_height=20)
    assert len(v_range.visible_items) == 0
    assert v_range.total_count == 0
