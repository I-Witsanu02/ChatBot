"""Utilities for building hierarchical topic trees from KB records."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _display_subcategory(raw: str | None) -> str | None:
    value = str(raw or '').strip()
    if not value or value.isdigit():
        return None
    return value


def build_topic_tree(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str | None, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in records:
        if str(row.get('status') or 'active') != 'active':
            continue
        category = str(row.get('category') or '').strip()
        question = str(row.get('question') or '').strip()
        if not category or not question:
            continue
        grouped[category][_display_subcategory(row.get('subcategory'))].append(row)

    tree: list[dict[str, Any]] = []
    for category, subgroups in grouped.items():
        category_node = {
            'id': category,
            'label': category,
            'type': 'category',
            'children': [],
        }
        # Put direct questions (no subcategory) first
        if None in subgroups:
            for row in subgroups[None]:
                category_node['children'].append({
                    'id': str(row.get('id') or question_slug(row.get('question', ''))),
                    'label': str(row.get('question') or '').strip(),
                    'type': 'topic',
                    'category': category,
                    'question': str(row.get('question') or '').strip(),
                })
        for subcategory, rows in subgroups.items():
            if subcategory is None:
                continue
            sub_node = {
                'id': f'{category}::{subcategory}',
                'label': subcategory,
                'type': 'subcategory',
                'category': category,
                'children': [],
            }
            for row in rows:
                sub_node['children'].append({
                    'id': str(row.get('id') or question_slug(row.get('question', ''))),
                    'label': str(row.get('question') or '').strip(),
                    'type': 'topic',
                    'category': category,
                    'question': str(row.get('question') or '').strip(),
                })
            category_node['children'].append(sub_node)
        tree.append(category_node)
    tree.sort(key=lambda n: n['label'])
    return tree


def question_slug(text: str) -> str:
    return ''.join(ch for ch in text.lower().replace(' ', '-') if ch.isalnum() or ch == '-')[:80]
