import json
import os
import shutil
import time
import requests
from pathlib import Path

VERSION = "0.1.2"
SUP = "http://supervisor"
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
H = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}
CFG = Path("/data/options.json")
STATE = Path("/data/fleet_state.json")


def get(path):
    try:
        r = requests.get(SUP + path, headers=H, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("data", data)
    except Exception as e:
        print(f"Supervisor GET {path}: {e!r}", flush=True)
        return {}


def loadcfg():
    return json.loads(CFG.read_text())


def loadstate():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def savestate(state):
    STATE.write_text(json.dumps(state))
    os.chmod(STATE, 0o600)


def enroll(cfg, state):
    code = cfg.get("enrollment_code", "").strip()

    if state.get("token") or not code:
        return state

    r = requests.post(
        cfg["fleet_url"].rstrip("/") + "/api/v1/enroll",
        json={"code": code},
        timeout=20,
    )
    r.raise_for_status()

    state.update(r.json())
    savestate(state)

    print("Enrollment successful", flush=True)
    return state


def cpu_usage():
    try:
        with open("/proc/loadavg") as f:
            load1 = float(f.read().split()[0])

        cpus = os.cpu_count() or 1
        return f"{min((load1 / cpus) * 100, 100):.1f}%"
    except Exception:
        return None


def memory_usage():
    try:
        values = {}

        with open("/proc/meminfo") as f:
            for line in f:
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0])

        total = values["MemTotal"]
        available = values["MemAvailable"]
        used = total - available

        percent = used / total * 100
        return f"{percent:.1f}%"
    except Exception:
        return None


def disk_usage():
    try:
        d = shutil.disk_usage("/")
        percent = d.used / d.total * 100
        return f"{percent:.1f}%"
    except Exception:
        return None


def collect_updates(core, sup, osinfo, addons):
    items = []

    def add(kind, name, installed, latest):
        if installed and latest and installed != latest:
            items.append({
                "type": kind,
                "name": name,
                "installed": str(installed),
                "latest": str(latest),
            })

    add(
        "core",
        "Home Assistant Core",
        core.get("version"),
        core.get("version_latest"),
    )

    add(
        "supervisor",
        "Supervisor",
        sup.get("version"),
        sup.get("version_latest"),
    )

    add(
        "os",
        "Home Assistant OS",
        osinfo.get("version"),
        osinfo.get("version_latest"),
    )

    if isinstance(addons, dict):
        for addon in addons.get("addons", []):
            if addon.get("update_available"):
                items.append({
                    "type": "app",
                    "name": addon.get("name") or addon.get("slug") or "App",
                    "installed": str(addon.get("version") or ""),
                    "latest": str(addon.get("version_latest") or ""),
                })

    return items


def heartbeat(cfg, state):
    core = get("/core/info")
    sup = get("/supervisor/info")
    osinfo = get("/os/info")
    addons = get("/addons")

    update_items = collect_updates(core, sup, osinfo, addons)

    payload = {
        "agent_version": VERSION,
        "ha_version": core.get("version"),
        "supervisor_version": sup.get("version"),
        "os_version": osinfo.get("version"),
        "updates": len(update_items),
        "update_items": update_items,
        "cpu": cpu_usage(),
        "memory": memory_usage(),
        "disk": disk_usage(),
    }

    r = requests.post(
        cfg["fleet_url"].rstrip("/") + "/api/v1/heartbeat",
        json=payload,
        headers={"Authorization": "Bearer " + state["token"]},
        timeout=20,
    )
    r.raise_for_status()

    print(
        f"Heartbeat OK: "
        f"HA={payload['ha_version']} "
        f"updates={payload['updates']} "
        f"cpu={payload['cpu']} "
        f"ram={payload['memory']} "
        f"disk={payload['disk']}",
        flush=True,
    )


while True:
    try:
        cfg = loadcfg()
        state = enroll(cfg, loadstate())

        if state.get("token"):
            heartbeat(cfg, state)

    except Exception as e:
        print("fleet-agent:", repr(e), flush=True)

    try:
        interval = int(loadcfg().get("interval_seconds", 60))
    except Exception:
        interval = 60

    time.sleep(max(30, interval))
