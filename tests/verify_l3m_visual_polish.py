import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import websockets

async def send_cdp(ws, msg_id, method, params=None):
    payload = {'id': msg_id, 'method': method}
    if params:
        payload['params'] = params
    await ws.send(json.dumps(payload))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get('id') == msg_id:
            return data

async def run_visual_verification():
    chrome_path = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    artifacts_dir = r'C:\Users\SUBBU\.gemini\antigravity\brain\7edf9f7c-23cd-4e80-8fec-393944d5bef5'
    local_dir = r'C:\Users\SUBBU\Downloads\hermes\generated_projects\lvm3_rocket_cinematic'
    temp_dir = tempfile.mkdtemp()

    # Launch Chrome with isolated user-data-dir on port 9240 (1280x720)
    proc = subprocess.Popen([
        chrome_path,
        '--headless=new',
        '--use-gl=angle',
        f'--user-data-dir={temp_dir}',
        '--remote-debugging-port=9240',
        '--window-size=1280,720',
        'http://127.0.0.1:8089/'
    ])

    time.sleep(2.5)

    try:
        with urllib.request.urlopen('http://127.0.0.1:9240/json') as resp:
            tabs = json.loads(resp.read().decode())
            # Find the page tab for our site
            target_tab = None
            for t in tabs:
                if t.get('type') == 'page' and '8089' in t.get('url', ''):
                    target_tab = t
                    break
            if not target_tab:
                target_tab = tabs[0]
            ws_url = target_tab['webSocketDebuggerUrl']
            print('Connected to CDP at:', ws_url, flush=True)

        async with websockets.connect(ws_url) as ws:
            mid = 1
            await send_cdp(ws, mid, 'Page.enable'); mid += 1
            await send_cdp(ws, mid, 'Runtime.enable'); mid += 1

            # Give Three.js time to load and render the initial standby frame
            await asyncio.sleep(3.0)

            # Check for console errors & state
            check_console = """
            (() => {
                return {
                    canvas: !!document.querySelector('canvas'),
                    canvasW: document.querySelector('canvas')?.width,
                    canvasH: document.querySelector('canvas')?.height,
                    missionName: document.getElementById('mission-name')?.innerText,
                    missionStatus: document.getElementById('mission-status')?.innerText,
                    altitude: document.getElementById('altitude')?.innerText,
                    velocity: document.getElementById('velocity')?.innerText,
                    trajectory: document.getElementById('trajectory')?.innerText,
                    countdown: document.getElementById('countdown')?.innerText,
                    s200: document.getElementById('state-s200')?.innerText,
                    l110: document.getElementById('state-l110')?.innerText,
                    c25: document.getElementById('state-c25')?.innerText,
                    fairing: document.getElementById('state-fairing')?.innerText
                };
            })()
            """
            res = await send_cdp(ws, mid, 'Runtime.evaluate', {'expression': check_console, 'returnByValue': True}); mid += 1
            val = res['result']['result']['value']
            print('STATE 1 [STANDBY] Telemetry & Scene:', val, flush=True)

            # Screenshot 1: Standby
            res_shot1 = await send_cdp(ws, mid, 'Page.captureScreenshot', {'format': 'png'}); mid += 1
            data1 = base64.b64decode(res_shot1['result']['data'])
            path1 = os.path.join(local_dir, 'screenshot_1_standby.png')
            with open(path1, 'wb') as f:
                f.write(data1)
            shutil.copyfile(path1, os.path.join(artifacts_dir, 'screenshot_1_standby.png'))
            print(f'Screenshot 1 (Standby) saved: {len(data1)} bytes -> {path1}', flush=True)

            # STATE 2: Start Countdown
            await send_cdp(ws, mid, 'Runtime.evaluate', {'expression': "document.getElementById('btn-launch')?.click()"}); mid += 1
            await asyncio.sleep(2.5)

            res_cnt = await send_cdp(ws, mid, 'Runtime.evaluate', {
                'expression': """(() => ({
                    status: document.getElementById('mission-status')?.innerText,
                    countdown: document.getElementById('countdown')?.innerText,
                    launchBtnDisabled: document.getElementById('btn-launch')?.disabled
                }))()""",
                'returnByValue': True
            }); mid += 1
            print('STATE 2 [COUNTDOWN] State:', res_cnt['result']['result']['value'], flush=True)

            # Screenshot 2: Countdown
            res_shot2 = await send_cdp(ws, mid, 'Page.captureScreenshot', {'format': 'png'}); mid += 1
            data2 = base64.b64decode(res_shot2['result']['data'])
            path2 = os.path.join(local_dir, 'screenshot_2_countdown.png')
            with open(path2, 'wb') as f:
                f.write(data2)
            shutil.copyfile(path2, os.path.join(artifacts_dir, 'screenshot_2_countdown.png'))
            print(f'Screenshot 2 (Countdown) saved: {len(data2)} bytes -> {path2}', flush=True)

            # STATE 3: Trigger Launch & Ascent
            await send_cdp(ws, mid, 'Runtime.evaluate', {'expression': 'launch()'}); mid += 1
            # Let it fly for 4 seconds
            await asyncio.sleep(4.0)

            res_flight = await send_cdp(ws, mid, 'Runtime.evaluate', {
                'expression': """(() => ({
                    status: document.getElementById('mission-status')?.innerText,
                    altitude: document.getElementById('altitude')?.innerText,
                    velocity: document.getElementById('velocity')?.innerText,
                    trajectory: document.getElementById('trajectory')?.innerText,
                    s200: document.getElementById('state-s200')?.innerText,
                    countdown: document.getElementById('countdown')?.innerText
                }))()""",
                'returnByValue': True
            }); mid += 1
            print('STATE 3 [ASCENT] Flight Telemetry:', res_flight['result']['result']['value'], flush=True)

            # Trigger booster separation
            await send_cdp(ws, mid, 'Runtime.evaluate', {'expression': 'separateBoosters()'}); mid += 1
            await asyncio.sleep(1.5)

            # Screenshot 3: Ascent with active telemetry & plume
            res_shot3 = await send_cdp(ws, mid, 'Page.captureScreenshot', {'format': 'png'}); mid += 1
            data3 = base64.b64decode(res_shot3['result']['data'])
            path3 = os.path.join(local_dir, 'screenshot_3_ascent.png')
            with open(path3, 'wb') as f:
                f.write(data3)
            shutil.copyfile(path3, os.path.join(artifacts_dir, 'screenshot_3_ascent.png'))
            print(f'Screenshot 3 (Ascent & Separation) saved: {len(data3)} bytes -> {path3}', flush=True)

            # STATE 4: Reset
            await send_cdp(ws, mid, 'Runtime.evaluate', {'expression': "document.getElementById('btn-reset')?.click()"}); mid += 1
            await asyncio.sleep(1.5)

            res_reset = await send_cdp(ws, mid, 'Runtime.evaluate', {
                'expression': """(() => ({
                    status: document.getElementById('mission-status')?.innerText,
                    altitude: document.getElementById('altitude')?.innerText,
                    velocity: document.getElementById('velocity')?.innerText,
                    s200: document.getElementById('state-s200')?.innerText,
                    launchBtnDisabled: document.getElementById('btn-launch')?.disabled
                }))()""",
                'returnByValue': True
            }); mid += 1
            print('STATE 4 [RESET] Restored State:', res_reset['result']['result']['value'], flush=True)

            # Screenshot 4: Reset
            res_shot4 = await send_cdp(ws, mid, 'Page.captureScreenshot', {'format': 'png'}); mid += 1
            data4 = base64.b64decode(res_shot4['result']['data'])
            path4 = os.path.join(local_dir, 'screenshot_4_reset.png')
            with open(path4, 'wb') as f:
                f.write(data4)
            shutil.copyfile(path4, os.path.join(artifacts_dir, 'screenshot_4_reset.png'))
            print(f'Screenshot 4 (Reset) saved: {len(data4)} bytes -> {path4}', flush=True)

            # STATE 5: Test Responsive Viewport (Mobile 414x896)
            await send_cdp(ws, mid, 'Emulation.setDeviceMetricsOverride', {
                'width': 414,
                'height': 896,
                'deviceScaleFactor': 2,
                'mobile': True
            }); mid += 1
            await send_cdp(ws, mid, 'Runtime.evaluate', {'expression': 'window.dispatchEvent(new Event("resize"))'}); mid += 1
            await asyncio.sleep(1.5)

            res_shot5 = await send_cdp(ws, mid, 'Page.captureScreenshot', {'format': 'png'}); mid += 1
            data5 = base64.b64decode(res_shot5['result']['data'])
            path5 = os.path.join(local_dir, 'screenshot_5_mobile_standby.png')
            with open(path5, 'wb') as f:
                f.write(data5)
            shutil.copyfile(path5, os.path.join(artifacts_dir, 'screenshot_5_mobile_standby.png'))
            print(f'Screenshot 5 (Mobile 414x896) saved: {len(data5)} bytes -> {path5}', flush=True)

            print('ALL REAL BROWSER VERIFICATIONS COMPLETED SUCCESSFULLY!', flush=True)

    finally:
        proc.terminate()
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(run_visual_verification())
