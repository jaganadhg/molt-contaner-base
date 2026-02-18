import asyncio, json, os, uuid

async def run(query="Cognizant"):
    import websockets
    token = os.environ.get('OPENCLAW_GATEWAY_TOKEN')
    if not token:
        # fallback to .env
        env = os.path.join(os.path.dirname(__file__), '.env')
        if os.path.isfile(env):
            with open(env) as f:
                for line in f:
                    if line.startswith('OPENCLAW_GATEWAY_TOKEN='):
                        token = line.split('=',1)[1].strip()
                        break
    if not token:
        print('ERROR: OPENCLAW_GATEWAY_TOKEN not set')
        return

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
            msg = await ws.recv()
            d = json.loads(msg)
            if d.get('type') == 'res' and d.get('id') == connect_msg['id'] and d.get('ok'):
                break

        chat_msg = {
            "type": "req",
            "method": "chat.send",
            "id": str(uuid.uuid4()),
            "params": {
                "sessionKey": f"main:{uuid.uuid4()}",
                "message": f"What's the latest news about {query}?",
                "idempotencyKey": str(uuid.uuid4())
            }
        }
        await ws.send(json.dumps(chat_msg))

        print(f'Sent UI-style query: "What\'s the latest news about {query}?"\n')
        final = None
        while True:
            msg = await ws.recv()
            d = json.loads(msg)
            t = d.get('type')
            if t == 'event':
                ev = d.get('event')
                payload = d.get('payload') or {}
                if ev == 'agent':
                    # show lifecycle and tool events
                    stream = payload.get('stream','')
                    data = payload.get('data', {})
                    if stream == 'tool':
                        print(f"[agent:tool] {data.get('phase','')} -> {data.get('name') or data.get('tool')}")
                    else:
                        print(f"[agent:{stream}] {data if len(str(data))<200 else str(data)[:200]+'...'}")
                elif ev == 'chat':
                    state = payload.get('state')
                    text = payload.get('message','')
                    if state == 'delta' and text:
                        print(text, end='', flush=True)
                    elif state == 'final':
                        final = text
                        print('\n\n=== FINAL MESSAGE ===\n')
                        print(final)
                        break
                else:
                    # other events (health/etc.)
                    pass
        return final

if __name__ == '__main__':
    asyncio.run(run())
