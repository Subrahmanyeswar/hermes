# scripts/read_m477_events.py
import urllib.request, json
req = urllib.request.Request('http://127.0.0.1:8765/api/missions/m_477caaa1/events/history')
try:
    with urllib.request.urlopen(req) as resp:
        events = json.loads(resp.read().decode()).get('events', [])
        print(f"Total events: {len(events)}")
        for e in events:
            et = e.get('event_type')
            p = e.get('payload', {})
            if et in ('TOOL_COMPLETED', 'ACTION_ALLOWED', 'AGENT_TURN_STARTED', 'AGENT_NO_PROGRESS', 'TIER_FAILOVER_STARTED'):
                tool = p.get('tool_name') or ''
                turn = p.get('turn_number') or ''
                args = str(p.get('arguments') or p.get('arguments_summary') or '')[:70]
                print(f"{et:20s} | turn={turn} tool={tool} | {args}")
except Exception as exc:
    print('Error:', exc)
