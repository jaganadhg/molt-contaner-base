import asyncio, json, uuid

async def run():
    import websockets
    token = None
    try:
        # try .env first
        from pathlib import Path
        p = Path('.env')
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith('OPENCLAW_GATEWAY_TOKEN='):
                    token = line.split('=',1)[1].strip()
                    break
    except Exception:
        token = None
    if not token:
        token = '3796d796c68d48772769775a8ae23cb01b2ec7c83f03a6f6fd39412dc886a23f'

    url = 'ws://localhost:18789/'
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
        # wait for connect response
        while True:
            d = json.loads(await ws.recv())
            if d.get('type') == 'res' and d.get('id') == connect_msg['id']:
                break
        # send explicit instruction to use topic-news-search
        chat_msg = {
            "type": "req",
            "method": "chat.send",
            "id": str(uuid.uuid4()),
            "params": {
                "sessionKey": f"main:{uuid.uuid4()}",
                "message": "Please run the skill `topic-news-search` — execute `node skills/topic-news-search/scripts/fetch_news.js \"Tesla\"` and return the results in the SKILL.md output format. If no results, reply that no recent news was found.",
                "idempotencyKey": str(uuid.uuid4())
            }
        }
        await ws.send(json.dumps(chat_msg))
        start = asyncio.get_event_loop().time()
        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=60)
                d = json.loads(msg)
                if d.get('type') == 'event' and d.get('event') == 'chat':
                    payload = d.get('payload', {})
                    state = payload.get('state')
                    text = payload.get('message','')
                    if state == 'delta' and text:
                        print(text, end='', flush=True)
                    elif state == 'final':
                        print('\n---\nFINAL MESSAGE:\n')
                        print(text)
                        break
            except asyncio.TimeoutError:
                print('\nTimeout waiting for agent response')
                break

if __name__=='__main__':
    asyncio.run(run())
