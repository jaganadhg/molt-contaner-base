import asyncio
import json
import os
import uuid

import pytest
import websockets


def _load_token():
    token = os.environ.get('OPENCLAW_GATEWAY_TOKEN')
    if token:
        return token
    env_path = os.path.join(os.path.dirname(__file__) or '.', '../../.env')
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('OPENCLAW_GATEWAY_TOKEN=') and not line.startswith('#'):
                    return line.split('=', 1)[1].strip()
    pytest.skip('OPENCLAW_GATEWAY_TOKEN not set')


async def _send_news_request(token: str, query: str = 'Cognizant') -> str:
    url = 'ws://127.0.0.1:18789/'
    async with websockets.connect(url, additional_headers={"Origin": "http://localhost:18789"}) as ws:
        connect_msg = {
            "type": "req",
            "method": "connect",
            "id": str(uuid.uuid4()),
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {"id": "openclaw-control-ui", "mode": "ui", "platform": "linux", "version": "1.0.0"},
                "auth": {"token": token},
                "role": "operator",
                "scopes": ["operator.write"]
            }
        }
        await ws.send(json.dumps(connect_msg))

        # wait for connect ok
        for _ in range(30):
            msg = await asyncio.wait_for(ws.recv(), timeout=2)
            d = json.loads(msg)
            if d.get('type') == 'res' and d.get('id') == connect_msg['id'] and d.get('ok'):
                break

        chat_msg = {
            "type": "req",
            "method": "chat.send",
            "id": str(uuid.uuid4()),
            "params": {
                "sessionKey": f"main:{uuid.uuid4()}",
                "message": f"Please run the skill `topic-news-search` and fetch the latest news for '{query}'. Do NOT use any browser or web.fetch tool; use only the skill.",
                "idempotencyKey": str(uuid.uuid4())
            }
        }
        await ws.send(json.dumps(chat_msg))

        final_text = None
        for _ in range(240):  # up to 120s
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            d = json.loads(msg)
            if d.get('type') == 'event' and d.get('event') == 'chat':
                payload = d.get('payload', {})
                state = payload.get('state')
                text = str(payload.get('message', ''))
                if state == 'final' and text:
                    final_text = text
                    break
        if final_text is None:
            pytest.fail('No final chat message received from agent')
        return final_text


def test_agent_uses_topic_news_search():
    token = _load_token()
    final = asyncio.run(_send_news_request(token, 'Cognizant'))

    # Agent MUST rely on the skill output (contains a heading and the query name)
    assert ('News for' in final) or ('Topic News Search Results' in final) or ('Cognizant' in final)
    # Ensure agent did not reply that it used a browser (explicit negative check)
    assert 'browser' not in final.lower() and 'web.fetch' not in final.lower()
