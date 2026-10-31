import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

with urllib.request.urlopen('http://127.0.0.1:8765/api/health') as r:
    health = json.loads(r.read())
print('=== 1. CONFIGURED MODEL STACK (from /api/health) ===')
for t, m in health.get('model_stack', {}).items():
    print(f'  {t}: {m}')

with urllib.request.urlopen('http://127.0.0.1:8765/api/missions/m_240bfce4/events/history') as r:
    hist = json.loads(r.read())

print('\n=== 2. REQUEST-LEVEL MODEL OPERATIONS (Mission m_240bfce4) ===')
for ev in hist.get('events', []):
    et = ev.get('event_type')
    p = ev.get('payload', {})
    if et in ('MODEL_REQUESTED', 'MODEL_COMPLETED', 'TIER_FAILOVER_STARTED'):
        lat = p.get('latency') or p.get('duration_ms')
        lat_str = f"{lat:.2f}s" if isinstance(lat, float) else f"{lat}ms" if lat else "N/A"
        seq = ev.get('sequence')
        tier = p.get('tier')
        prov = p.get('provider')
        mod = p.get('model')
        print(f"  Seq {seq:>5} | {et:<21} | Tier: {tier} | Provider: {prov} | Model: {mod} | Latency: {lat_str}")
