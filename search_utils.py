"""Utilities for expanding search queries with synonyms.

This module provides a small built-in English synonym map and a helper
function to expand a user query so that searches will also match known
synonyms.  The map intentionally remains tiny to keep the repository
lightweight while demonstrating synonym expansion.
"""

from __future__ import annotations

import re
from typing import Dict, List

# A minimal English synonym dictionary used for search expansion.
# Only a handful of common terms are included to keep the dependency
# footprint small.
SYNONYM_MAP: Dict[str, List[str]] = {
    "fast": ["quick", "rapid", "speedy"],
    "quick": ["fast", "rapid", "speedy"],
    "rapid": ["fast", "quick", "speedy"],
    "speedy": ["fast", "quick", "rapid"],
}


def expand_with_synonyms(query: str) -> str:
    """Expand a search query to include known synonyms.

    Each word in the query is replaced with an ``OR`` group containing the
    word itself and any synonyms from :data:`SYNONYM_MAP`.  This string is
    suitable for use with SQLite's FTS ``MATCH`` operator.
    """

    tokens = re.findall(r"\w+", query)
    parts: List[str] = []
    for token in tokens:
        synonyms = SYNONYM_MAP.get(token.lower())
        if synonyms:
            group = " OR ".join([token] + synonyms)
            parts.append(f"({group})")
        else:
            parts.append(token)
    return " ".join(parts) if parts else query
