from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.topic_tree import build_topic_tree


def test_build_topic_tree_groups_category_and_topics():
    rows = [
        {'id': '1', 'category': 'วัคซีน', 'subcategory': 'บริการ', 'question': 'วัคซีนไข้หวัดใหญ่', 'status': 'active'},
        {'id': '2', 'category': 'วัคซีน', 'subcategory': 'บริการ', 'question': 'วัคซีนตับอักเสบบี', 'status': 'active'},
        {'id': '3', 'category': 'คลินิกทันตกรรม', 'subcategory': None, 'question': 'ติดต่อทันตกรรม', 'status': 'active'},
    ]
    tree = build_topic_tree(rows)
    labels = [n['label'] for n in tree]
    assert 'วัคซีน' in labels
    assert 'คลินิกทันตกรรม' in labels
    vaccine = [n for n in tree if n['label'] == 'วัคซีน'][0]
    assert vaccine['children'][0]['type'] == 'subcategory'
    assert any(child['label'] == 'วัคซีนไข้หวัดใหญ่' for child in vaccine['children'][0]['children'])
