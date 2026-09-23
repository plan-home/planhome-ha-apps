import json
import os
import shutil
import time
import requests
from pathlib import Path

VERSION = "0.2.2"
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



def ha_get(path):
    try:
        r = requests.get(
            SUP + "/core/api" + path,
            headers=H,
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Home Assistant API GET {path}: {e!r}", flush=True)
        return []


def collect_ha_updates():
    states = ha_get("/states")

    if not isinstance(states, list):
        return []

    items = []

    system_ids = {
        "update.home_assistant_core_update",
        "update.home_assistant_operating_system_update",
        "update.home_assistant_supervisor_update",
    }

    for row in states:
        if not isinstance(row, dict):
            continue

        entity_id = str(row.get("entity_id") or "")

        if not entity_id.startswith("update."):
            continue

        if entity_id in system_ids:
            continue

        # HA ist maßgeblich: nur state=on bedeutet Update verfügbar.
        if str(row.get("state") or "").lower() != "on":
            continue

        attrs = row.get("attributes") or {}
        latest = attrs.get("latest_version")

        if not latest:
            continue

        release_url = str(attrs.get("release_url") or "")
        if not release_url.startswith(("https://", "http://")):
            release_url = ""

        items.append({
            "type": "ha_update",
            "name": str(attrs.get("friendly_name") or entity_id),
            "installed": str(attrs.get("installed_version") or ""),
            "latest": str(latest),
            "entity_id": entity_id,
            "category": str(attrs.get("device_class") or "integration"),
            "release_url": release_url[:1000],
        })

    return items


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

    def add_supervisor_update(kind, name, info):
        # Supervisor is authoritative: version_latest alone is not an offered update.
        if not isinstance(info, dict) or info.get("update_available") is not True:
            return
        installed = info.get("version")
        latest = info.get("version_latest")
        if installed and latest:
            items.append({
                "type": kind,
                "name": name,
                "installed": str(installed),
                "latest": str(latest),
            })

    add_supervisor_update("core", "Home Assistant Core", core)
    add_supervisor_update("supervisor", "Supervisor", sup)
    add_supervisor_update("os", "Home Assistant OS", osinfo)

    if isinstance(addons, dict):
        for addon in addons.get("addons", []):
            if addon.get("update_available") is True:
                items.append({
                    "type": "app",
                    "name": addon.get("name") or addon.get("slug") or "App",
                    "installed": str(addon.get("version") or ""),
                    "latest": str(addon.get("version_latest") or ""),
                    "slug": addon.get("slug") or "",
                })

    return items


def heartbeat(cfg, state):
    core = get("/core/info")
    sup = get("/supervisor/info")
    osinfo = get("/os/info")
    addons = get("/addons")
    backups = get("/backups/info")
    resolution = get("/resolution/info")

    update_items = collect_updates(core, sup, osinfo, addons)
    update_items.extend(collect_ha_updates())
    backup_rows = backups.get("backups",[]) if isinstance(backups,dict) else []
    backup_dates = sorted([str(b.get("date")) for b in backup_rows if b.get("date")], reverse=True)
    issues = resolution.get("issues",[]) if isinstance(resolution,dict) else []

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
        "backup_count": len(backup_rows),
        "backup_last_at": backup_dates[0] if backup_dates else None,
        "repair_count": len(issues),
        "diagnostics": {
            "unsupported": resolution.get("unsupported",[]) if isinstance(resolution,dict) else [],
            "unhealthy": resolution.get("unhealthy",[]) if isinstance(resolution,dict) else [],
            "issues": issues[:25],
        },
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


def sup_post(path, payload=None, timeout=1800):
    r=requests.post(SUP+path,headers=H,json=payload or {},timeout=timeout)
    r.raise_for_status()
    try:
        data=r.json()
        if data.get("result") not in (None,"ok"):
            raise RuntimeError(data.get("message") or data)
        return data.get("data",data)
    except ValueError:
        return {"http_status":r.status_code}

def command_channel(cfg, state):
    base=cfg["fleet_url"].rstrip("/")
    headers={"Authorization":"Bearer "+state["token"]}
    r=requests.get(base+"/api/v1/commands/next",headers=headers,timeout=20)
    r.raise_for_status(); cmd=r.json().get("command")
    if not cmd:return
    cid=cmd.get("id"); ctype=cmd.get("type"); payload=cmd.get("payload") or {}
    status="completed"; result={"agent_version":VERSION}
    try:
        if ctype=="ping":
            result["message"]="pong"
        elif ctype=="backup_full":
            name="Plan@Home Fleet "+time.strftime("%Y-%m-%d %H:%M")
            result["backup"]=sup_post("/backups/new/full",{"name":name,"compressed":True,"background":False},1800)
        elif ctype=="core_restart":
            result["restart"]=sup_post("/core/restart",{},120)
        elif ctype=="maintenance_update":
            kind=payload.get("kind"); version=str(payload.get("version") or ""); slug=str(payload.get("slug") or "")
            if kind not in ("core","app") or not version:
                raise ValueError("invalid update payload")
            name="Plan@Home Fleet pre-update "+time.strftime("%Y-%m-%d %H:%M")
            result["backup"]=sup_post("/backups/new/full",{"name":name,"compressed":True,"background":False},1800)
            if kind=="core":
                result["update"]=sup_post("/core/update",{"version":version,"backup":False},1800)
            else:
                if not slug or "/" in slug or ".." in slug: raise ValueError("invalid app slug")
                result["update"]=sup_post("/store/addons/"+slug+"/update",{"backup":False,"background":False},1800)
            result["target"]={"kind":kind,"version":version,"slug":slug}
        else:
            raise ValueError("command type disabled")
    except Exception as e:
        status="failed"; result["error"]=repr(e)[:2000]
    ar=requests.post(base+f"/api/v1/commands/{cid}/ack",headers=headers,
        json={"status":status,"result":result},timeout=30)
    ar.raise_for_status()
    print(f"Command {ctype} {cid}: {status}",flush=True)


while True:
    try:
        cfg = loadcfg()
        state = enroll(cfg, loadstate())

        if state.get("token"):
            heartbeat(cfg, state)
            command_channel(cfg, state)

    except Exception as e:
        print("fleet-agent:", repr(e), flush=True)

    try:
        interval = int(loadcfg().get("interval_seconds", 60))
    except Exception:
        interval = 60

    time.sleep(max(30, interval))
