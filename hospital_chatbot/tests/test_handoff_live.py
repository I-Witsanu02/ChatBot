from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pathlib import Path
import tempfile

from backend.handoff import append_live_message, claim_ticket, create_handoff_ticket, fetch_session_responses_after


def test_live_message_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / 'analytics.db'
        ticket_id = create_handoff_ticket(db, session_id='s1', question='ทดสอบ', category='วัคซีน', confidence=0.2, route='fallback', reason='low_conf')
        claim = claim_ticket(db, ticket_id=ticket_id, responder='admin1')
        assert claim['status'] == 'in_progress'
        msg = append_live_message(db, ticket_id=ticket_id, responder='admin1', message_text='ตอบสด', close_ticket=False)
        items = fetch_session_responses_after(db, 's1', after_id=0)
        assert items and items[0]['response_text'] == 'ตอบสด'
        assert msg['ticket_id'] == ticket_id
