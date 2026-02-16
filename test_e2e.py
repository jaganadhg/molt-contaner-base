#!/usr/bin/env python3
"""End-to-end test: send a chat message via WebSocket and wait for agent response."""
import asyncio, json, os, sys, time, uuid


def _load_token():
    """Read gateway token from OPENCLAW_GATEWAY_TOKEN env var or .env file."""
    token = os.environ.get('OPENCLAW_GATEWAY_TOKEN')
    if token:
        return token
    env_path = os.path.join(os.path.dirname(__file__) or '.', '.env')
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith('OPENCLAW_GATEWAY_TOKEN=') and not line.startswith('#'):
                    return line.split('=', 1)[1].strip()
    print('ERROR: Set OPENCLAW_GATEWAY_TOKEN env var or ensure .env file exists.')
    sys.exit(1)


async def test():
    try:
        import websockets
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'websockets', '-q'])
        import websockets

    token = _load_token()
    url = f'ws://localhost:18789/'

    print(f'Connecting to {url}...')
    async with websockets.connect(
        url,
        ping_interval=30,
        additional_headers={"Origin": "http://localhost:18789"},
        max_size=10*1024*1024,
    ) as ws:
        print('WebSocket connected!')

        # Step 1: Send connect handshake (required first message)
        # Protocol: type="req", method="connect"
        connect_msg = {
            "type": "req",
            "method": "connect",
            "id": str(uuid.uuid4()),
            "params": {
                "minProtocol": 3,
                "maxProtocol": 3,
                "client": {
                    "id": "openclaw-control-ui",
                    "mode": "ui",
                    "platform": "linux",
                    "version": "1.0.0"
                },
                "auth": {
                    "token": token
                },
                "role": "operator",
                "scopes": ["operator.write"]
            }
        }
        await ws.send(json.dumps(connect_msg))
        print(f'Sent connect handshake')

        # Wait for hello response
        hello_received = False
        for _ in range(30):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
                d = json.loads(msg)
                frame_type = d.get('type', '')
                
                # Response to our connect request
                if frame_type == 'res' and d.get('id') == connect_msg['id']:
                    if d.get('ok'):
                        print(f'  Connect OK: hello received')
                        hello_received = True
                    else:
                        print(f'  Connect ERROR: {json.dumps(d.get("error", {}))[:200]}')
                        return
                elif frame_type == 'event':
                    print(f'  Event: {d.get("event", "?")}')
            except asyncio.TimeoutError:
                break

        if not hello_received:
            print('ERROR: No hello response after connect')
            return

        # Drain any remaining init events
        for _ in range(20):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                d = json.loads(msg)
                t = d.get('type', '')
                event = d.get('event', d.get('method', ''))
                if t or event:
                    print(f'  Event: {t}/{event}')
            except asyncio.TimeoutError:
                break

        # Step 2: Send chat message (type="req", method="chat.send")
        session_key = f"main:{uuid.uuid4()}"
        chat_msg = {
            "type": "req",
            "method": "chat.send",
            "id": str(uuid.uuid4()),
            "params": {
                "sessionKey": session_key,
                "message": "What is the latest news about Tesla?",
                "idempotencyKey": str(uuid.uuid4())
            }
        }
        await ws.send(json.dumps(chat_msg))
        print(f'\nSent chat: "{chat_msg["params"]["message"]}"')
        print('Waiting for agent response (may take several minutes on CPU)...\n')

        start = time.time()
        got_response = False
        for _ in range(1200):  # up to 10 minutes
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                d = json.loads(msg)
                frame_type = d.get('type', '')
                
                # Response frame to our chat request
                if frame_type == 'res' and d.get('id') == chat_msg['id']:
                    if d.get('ok'):
                        payload = d.get('payload', {})
                        elapsed = time.time() - start
                        print(f'  Chat acknowledged ({elapsed:.1f}s): {json.dumps(payload)[:200]}')
                    else:
                        error = d.get('error', {})
                        print(f'  Chat ERROR: {json.dumps(error)[:300]}')
                        got_response = True

                # Event frames (agent events, chat events)
                elif frame_type == 'event':
                    event_name = d.get('event', '')
                    payload = d.get('payload', {})
                    payload_str = json.dumps(payload)
                    elapsed = time.time() - start
                    
                    # Log ALL events for debugging
                    if event_name == 'chat':
                        state = payload.get('state', '')
                        msg_text = str(payload.get('message', ''))
                        err = payload.get('errorMessage', '')
                        if state == 'delta' and msg_text:
                            print(f'{msg_text}', end='', flush=True)
                        elif state == 'final':
                            print(f'\n\n  === FINAL ({elapsed:.1f}s) ===')
                            print(f'  stopReason={payload.get("stopReason","")}')
                            print(f'  usage={json.dumps(payload.get("usage",{}))}')
                            if msg_text:
                                print(f'  message={msg_text[:500]}')
                            got_response = True
                        elif state == 'error':
                            print(f'\n  CHAT ERROR ({elapsed:.1f}s): {err}')
                            got_response = True
                        else:
                            print(f'\n  chat/{state} ({elapsed:.1f}s): {str(payload)[:200]}')
                    elif event_name == 'agent':
                        stream = payload.get('stream', '')
                        data = payload.get('data', {})
                        phase = data.get('phase', '')
                        tool = data.get('name', data.get('tool', ''))
                        if stream == 'lifecycle':
                            print(f'  [{elapsed:.0f}s] agent {phase}')
                        elif stream == 'tool':
                            print(f'  [{elapsed:.0f}s] tool {phase}: {tool}')
                        else:
                            print(f'  [{elapsed:.0f}s] agent/{stream}: {str(data)[:150]}')
                    elif event_name in ('health', 'tick', 'presence'):
                        pass  # skip noise
                    else:
                        print(f'  [{elapsed:.0f}s] {event_name}: {str(payload)[:200]}')

                if got_response:
                    # Drain a few more messages
                    for _ in range(10):
                        try:
                            extra = await asyncio.wait_for(ws.recv(), timeout=1)
                            ed = json.loads(extra)
                            if ed.get('type') == 'event' and ed.get('payload', {}).get('text'):
                                print(f'  Extra [{ed["event"]}]: {ed["payload"]["text"][:200]}')
                        except:
                            break
                    break
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                print(f'  Exception: {e}')
                break

        if not got_response:
            elapsed = time.time() - start
            print(f'\nNo text response after {elapsed:.1f}s')
            print('Check: podman logs --tail 20 openclaw-gateway')

        print('\nDone.')

asyncio.run(test())
