import asyncio
import httpx
import json
import time
import subprocess

def get_vram():
    try:
        out = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,memory.total,utilization.gpu', '--format=csv,noheader,nounits'], encoding='utf-8').strip()
        parts = [float(p.strip()) for p in out.split(',')]
        return {'used_mb': parts[0], 'total_mb': parts[1], 'gpu_util': parts[2]}
    except Exception as e:
        return {'error': str(e)}

async def run_measurement():
    client = httpx.AsyncClient(timeout=180.0)
    url = 'http://127.0.0.1:11434/api/generate'
    prompt = 'Return 42.'

    print('Initial VRAM:', get_vram())

    # Step 0: Force unload any resident model
    print('Unloading existing models...')
    await client.post(url, json={'model': 'deepseek-r1:8b', 'keep_alive': 0, 'stream': False})
    await client.post(url, json={'model': 'qwen3:8b', 'keep_alive': 0, 'stream': False})
    await asyncio.sleep(2)
    vram_unloaded = get_vram()
    print('Unloaded VRAM:', vram_unloaded)

    # Step 1: Cold T1 (deepseek-r1:8b)
    print('\n--- Step 1: Cold T1 (deepseek-r1:8b) ---')
    t0 = time.perf_counter()
    r1 = await client.post(url, json={'model': 'deepseek-r1:8b', 'prompt': prompt, 'keep_alive': '300s', 'stream': False, 'options': {'num_predict': 64}})
    t1_cold_wall = time.perf_counter() - t0
    d1 = r1.json()
    vram_t1 = get_vram()
    load1_ms = d1.get('load_duration', 0) / 1e6
    prompt_eval1_ms = d1.get('prompt_eval_duration', 0) / 1e6
    eval1_ms = d1.get('eval_duration', 0) / 1e6
    eval_count1 = d1.get('eval_count', 0)
    print(f'Cold T1: Wall={t1_cold_wall:.3f}s | Load={load1_ms:.1f}ms | Prefill={prompt_eval1_ms:.1f}ms | Eval={eval1_ms:.1f}ms | Tokens={eval_count1} | VRAM={vram_t1}')

    # Step 2: Warm T1 (deepseek-r1:8b)
    print('\n--- Step 2: Warm T1 (deepseek-r1:8b) ---')
    t0 = time.perf_counter()
    r2 = await client.post(url, json={'model': 'deepseek-r1:8b', 'prompt': prompt, 'keep_alive': '300s', 'stream': False, 'options': {'num_predict': 64}})
    t1_warm_wall = time.perf_counter() - t0
    d2 = r2.json()
    load2_ms = d2.get('load_duration', 0) / 1e6
    prompt_eval2_ms = d2.get('prompt_eval_duration', 0) / 1e6
    eval2_ms = d2.get('eval_duration', 0) / 1e6
    eval_count2 = d2.get('eval_count', 0)
    print(f'Warm T1: Wall={t1_warm_wall:.3f}s | Load={load2_ms:.1f}ms | Prefill={prompt_eval2_ms:.1f}ms | Eval={eval2_ms:.1f}ms | Tokens={eval_count2}')

    # Step 3: T1 -> T2 switch (qwen3:8b)
    print('\n--- Step 3: T1 -> T2 switch (qwen3:8b) ---')
    t0 = time.perf_counter()
    r3 = await client.post(url, json={'model': 'qwen3:8b', 'prompt': prompt, 'keep_alive': '300s', 'stream': False, 'options': {'num_predict': 64}})
    t1_t2_wall = time.perf_counter() - t0
    d3 = r3.json()
    vram_t2 = get_vram()
    load3_ms = d3.get('load_duration', 0) / 1e6
    prompt_eval3_ms = d3.get('prompt_eval_duration', 0) / 1e6
    eval3_ms = d3.get('eval_duration', 0) / 1e6
    eval_count3 = d3.get('eval_count', 0)
    print(f'T1->T2 Switch: Wall={t1_t2_wall:.3f}s | Load={load3_ms:.1f}ms | Prefill={prompt_eval3_ms:.1f}ms | Eval={eval3_ms:.1f}ms | Tokens={eval_count3} | VRAM={vram_t2}')

    # Step 4: Warm T2 (qwen3:8b)
    print('\n--- Step 4: Warm T2 (qwen3:8b) ---')
    t0 = time.perf_counter()
    r4 = await client.post(url, json={'model': 'qwen3:8b', 'prompt': prompt, 'keep_alive': '300s', 'stream': False, 'options': {'num_predict': 64}})
    t2_warm_wall = time.perf_counter() - t0
    d4 = r4.json()
    load4_ms = d4.get('load_duration', 0) / 1e6
    eval_count4 = d4.get('eval_count', 0)
    print(f'Warm T2: Wall={t2_warm_wall:.3f}s | Load={load4_ms:.1f}ms | Tokens={eval_count4}')

    # Step 5: T2 -> T1 switch (deepseek-r1:8b)
    print('\n--- Step 5: T2 -> T1 switch (deepseek-r1:8b) ---')
    t0 = time.perf_counter()
    r5 = await client.post(url, json={'model': 'deepseek-r1:8b', 'prompt': prompt, 'keep_alive': '300s', 'stream': False, 'options': {'num_predict': 64}})
    t2_t1_wall = time.perf_counter() - t0
    d5 = r5.json()
    vram_back_t1 = get_vram()
    load5_ms = d5.get('load_duration', 0) / 1e6
    prompt_eval5_ms = d5.get('prompt_eval_duration', 0) / 1e6
    eval5_ms = d5.get('eval_duration', 0) / 1e6
    eval_count5 = d5.get('eval_count', 0)
    print(f'T2->T1 Switch: Wall={t2_t1_wall:.3f}s | Load={load5_ms:.1f}ms | Prefill={prompt_eval5_ms:.1f}ms | Eval={eval5_ms:.1f}ms | Tokens={eval_count5} | VRAM={vram_back_t1}')

    res = {
        'vram_unloaded': vram_unloaded,
        'cold_t1': {'wall_s': t1_cold_wall, 'load_ms': load1_ms, 'prefill_ms': prompt_eval1_ms, 'eval_ms': eval1_ms, 'tokens': eval_count1, 'vram': vram_t1},
        'warm_t1': {'wall_s': t1_warm_wall, 'load_ms': load2_ms, 'prefill_ms': prompt_eval2_ms, 'eval_ms': eval2_ms, 'tokens': eval_count2},
        't1_to_t2_switch': {'wall_s': t1_t2_wall, 'load_ms': load3_ms, 'prefill_ms': prompt_eval3_ms, 'eval_ms': eval3_ms, 'tokens': eval_count3, 'vram': vram_t2},
        'warm_t2': {'wall_s': t2_warm_wall, 'load_ms': load4_ms, 'tokens': eval_count4},
        't2_to_t1_switch': {'wall_s': t2_t1_wall, 'load_ms': load5_ms, 'prefill_ms': prompt_eval5_ms, 'eval_ms': eval5_ms, 'tokens': eval_count5, 'vram': vram_back_t1}
    }
    with open('artifacts/performance/switch_and_residency_data.json', 'w', encoding='utf-8') as f:
        json.dump(res, f, indent=2)
    print('\nSwitch forensics saved to artifacts/performance/switch_and_residency_data.json')

if __name__ == '__main__':
    asyncio.run(run_measurement())
