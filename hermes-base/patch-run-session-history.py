"""Add opt-in durable history to the pinned Hermes /v1/runs endpoint.

The upstream endpoint treats session_id as persistence identity, not a request
to resume history. Keep its stateless default and explicit-history precedence.
Fail the image build on source drift so a runtime upgrade requires review.
"""

import sys
from pathlib import Path

ANCHOR = '        session_id = body.get("session_id") or stored_session_id\n'
RESUME = '''        # Agent Barn: resume persisted DM/thread context without flattening tools.
        if body.get("resume_session") is True:
            if not session_id or not isinstance(session_id, str):
                return web.json_response(_openai_error("resume_session requires session_id"), status=400)
            if "conversation_history" in body or previous_response_id or isinstance(raw_input, list):
                return web.json_response(_openai_error("resume_session cannot be combined with explicit history"), status=400)
            db = await self._ensure_session_db_async()
            if db is None:
                return web.json_response(_openai_error("Session database unavailable"), status=503)
            # Follow compaction lineage, preserving native tool-call metadata and
            # summary markers. Read errors must fail, never start an empty turn.
            session_id = await asyncio.to_thread(db.resolve_resume_session_id, session_id)
            conversation_history = await asyncio.to_thread(db.get_messages_as_conversation, session_id)
'''


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/opt/hermes/gateway/platforms/api_server.py')
    source = target.read_text()
    if ANCHOR + RESUME in source:
        return
    if source.count(ANCHOR) != 1:
        raise SystemExit('Hermes /v1/runs source changed; review the session history patch')
    patched = source.replace(ANCHOR, ANCHOR + RESUME)
    compile(patched, str(target), 'exec')
    target.write_text(patched)


if __name__ == '__main__':
    main()
