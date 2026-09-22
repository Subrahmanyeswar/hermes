"""
Hardware and software environment capture utility for Phase 3.
"""
import subprocess
import sys
import os
import platform
import json
import psutil

def get_gpu_info():
    info = {"name": "Unknown", "driver": "Unknown", "vram_total_mb": 0.0, "vram_used_mb": 0.0, "compute_cap": "Unknown", "pstate": "Unknown"}
    try:
        cmd = ["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used,compute_cap,pstate", "--format=csv,noheader,nounits"]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if res.returncode == 0 and res.stdout.strip():
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) >= 6:
                info["name"] = parts[0]
                info["driver"] = parts[1]
                info["vram_total_mb"] = float(parts[2])
                info["vram_used_mb"] = float(parts[3])
                info["compute_cap"] = parts[4]
                info["pstate"] = parts[5]
    except Exception as e:
        info["error"] = str(e)
    return info

def get_system_snapshot():
    gpu = get_gpu_info()
    mem = psutil.virtual_memory()
    return {
        "os": platform.platform(),
        "python_version": sys.version,
        "cpu_count_logical": psutil.cpu_count(logical=True),
        "cpu_count_physical": psutil.cpu_count(logical=False),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_available_gb": round(mem.available / (1024**3), 2),
        "gpu_name": gpu.get("name"),
        "gpu_driver": gpu.get("driver"),
        "gpu_vram_total_mb": gpu.get("vram_total_mb"),
        "gpu_vram_used_mb": gpu.get("vram_used_mb"),
        "gpu_compute_capability": gpu.get("compute_cap"),
    }

if __name__ == "__main__":
    snap = get_system_snapshot()
    print(json.dumps(snap, indent=2))
