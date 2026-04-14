"""Selector Registry - maps logical element names to CSS/XPath/text selectors."""

from __future__ import annotations

from src.config.models import SelectorEntry


class SelectorRegistry:
    """Decouples page interaction code from hardcoded selectors.

    All selectors live in config/selectors.yaml. Page objects call
    registry.get("page_name", "element_name") to get a SelectorEntry.
    """

    def __init__(self, data: dict) -> None:
        self._data = data

    def get(self, page_name: str, element_name: str) -> SelectorEntry:
        page = self._data.get(page_name)
        if page is None:
            raise KeyError(f"Selector page not found: {page_name}")
        entry = page.get(element_name)
        if entry is None:
            raise KeyError(
                f"Selector not found: {page_name}.{element_name}"
            )
        if isinstance(entry, dict):
            return SelectorEntry(**entry)
        raise TypeError(
            f"Invalid selector format for {page_name}.{element_name}"
        )

    def get_nested(
        self, page_name: str, group: str, element_name: str
    ) -> SelectorEntry:
        """Get a selector from a nested group (e.g., row_columns.username)."""
        page = self._data.get(page_name)
        if page is None:
            raise KeyError(f"Selector page not found: {page_name}")
        grp = page.get(group)
        if grp is None:
            raise KeyError(f"Selector group not found: {page_name}.{group}")
        entry = grp.get(element_name)
        if entry is None:
            raise KeyError(
                f"Selector not found: {page_name}.{group}.{element_name}"
            )
        if isinstance(entry, dict):
            return SelectorEntry(**entry)
        raise TypeError(
            f"Invalid selector format for {page_name}.{group}.{element_name}"
        )
