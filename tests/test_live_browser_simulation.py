import asyncio
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
import websockets

async def send_and_wait(ws, msg_id, method, params=None):
    payload = {'id': msg_id, 'method': method}
    if params:
        payload['params'] = params
    await ws.send(json.dumps(payload))
    while True:
        raw = await ws.recv()
        data = json.loads(raw)
        if data.get('id') == msg_id:
            return data

def test_live_simulation():
    chrome_path = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    proc = subprocess.Popen([
        chrome_path,
        '--headless=new',
        '--remote-debugging-port=9224',
        '--window-size=1920,1080',
        'http://127.0.0.1:8089/'
    ])

    time.sleep(2)
    try:
        with urllib.request.urlopen('http://127.0.0.1:9224/json') as resp:
            tabs = json.loads(resp.read().decode())
            ws_url = tabs[0]['webSocketDebuggerUrl']
            print('CDP URL:', ws_url)

        async def run_cdp():
            async with websockets.connect(ws_url) as ws:
                await send_and_wait(ws, 1, 'Page.enable')
                await send_and_wait(ws, 2, 'Runtime.enable')

                # Wait 2 seconds for Three.js render
                await asyncio.sleep(2.5)

                # Query page state
                eval_script = """
                (() => {
                    return {
                        mission: document.getElementById('mission-name')?.innerText,
                        status: document.getElementById('mission-status')?.innerText,
                        altitude: document.getElementById('altitude')?.innerText,
                        velocity: document.getElementById('velocity')?.innerText,
                        countdown: document.getElementById('countdown')?.innerText,
                        hasCanvas: !!document.querySelector('canvas'),
                        canvasWidth: document.querySelector('canvas')?.width,
                        canvasHeight: document.querySelector('canvas')?.height
                    };
                })()
                """
                res = await send_and_wait(ws, 3, 'Runtime.evaluate', {'expression': eval_script, 'returnByValue': True})
                print('Initial Page State:', res['result']['result']['value'])

                # Take initial screenshot
                res_shot = await send_and_wait(ws, 4, 'Page.captureScreenshot', {'format': 'png'})
                img_data = base64.b64decode(res_shot['result']['data'])
                shot_path = os.path.abspath('generated_projects/lvm3_rocket_cinematic/live_cdp_standby.png')
                with open(shot_path, 'wb') as f:
                    f.write(img_data)
                print(f'Standby Screenshot saved: {len(img_data)} bytes -> {shot_path}')

                # Click Launch
                click_launch = "document.getElementById('btn-launch')?.click()"
                await send_and_wait(ws, 5, 'Runtime.evaluate', {'expression': click_launch})

                # Wait for countdown
                await asyncio.sleep(2.5)
                check_countdown = "document.getElementById('countdown')?.innerText"
                res_cnt = await send_and_wait(ws, 6, 'Runtime.evaluate', {'expression': check_countdown, 'returnByValue': True})
                print('Countdown during active sequence:', res_cnt['result']['result']['value'])

                # Capture active countdown / launch screenshot
                res_shot2 = await send_and_wait(ws, 7, 'Page.captureScreenshot', {'format': 'png'})
                img_data2 = base64.b64decode(res_shot2['result']['data'])
                shot2_path = os.path.abspath('generated_projects/lvm3_rocket_cinematic/live_cdp_active.png')
                with open(shot2_path, 'wb') as f:
                    f.write(img_data2)
                print(f'Active Launch Screenshot saved: {len(img_data2)} bytes -> {shot2_path}')

                # Copy to artifact folder
                artifact_dir = r'C:\Users\SUBBU\.gemini\antigravity\brain\7edf9f7c-23cd-4e80-8fec-393944d5bef5'
                shutil.copyfile(shot_path, os.path.join(artifact_dir, 'live_cdp_standby.png'))
                shutil.copyfile(shot2_path, os.path.join(artifact_dir, 'live_cdp_active.png'))
                print('Successfully copied live screenshots to artifact directory.')

        asyncio.run(run_cdp())
    finally:
        proc.terminate()

if __name__ == '__main__':
    test_live_simulation()
