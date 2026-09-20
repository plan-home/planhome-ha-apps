import json, os, time, requests
from pathlib import Path
VERSION="0.1.0"
SUP="http://supervisor"
TOKEN=os.environ.get("SUPERVISOR_TOKEN","")
H={"Authorization":f"Bearer {TOKEN}","Content-Type":"application/json"}
CFG=Path('/data/options.json')
STATE=Path('/data/fleet_state.json')

def get(path):
    try:
        r=requests.get(SUP+path,headers=H,timeout=15); r.raise_for_status(); return r.json().get('data',r.json())
    except Exception: return {}

def loadcfg(): return json.loads(CFG.read_text())
def loadstate():
    try:return json.loads(STATE.read_text())
    except:return {}
def savestate(x): STATE.write_text(json.dumps(x))

def enroll(cfg,state):
    code=cfg.get('enrollment_code','').strip()
    if state.get('token') or not code:return state
    r=requests.post(cfg['fleet_url'].rstrip('/')+'/api/v1/enroll',json={'code':code},timeout=20); r.raise_for_status()
    state.update(r.json()); savestate(state); print('Enrollment successful',flush=True); return state

def heartbeat(cfg,state):
    core=get('/core/info'); sup=get('/supervisor/info'); osinfo=get('/os/info'); updates=get('/resolution/info')
    addons=get('/addons'); upd_count=0
    if isinstance(addons,dict):
        for a in addons.get('addons',[]): upd_count += 1 if a.get('update_available') else 0
    if core.get('version_latest') and core.get('version') != core.get('version_latest'): upd_count += 1
    if osinfo.get('version_latest') and osinfo.get('version') != osinfo.get('version_latest'): upd_count += 1
    payload={'agent_version':VERSION,'ha_version':core.get('version'),'supervisor_version':sup.get('version'),'os_version':osinfo.get('version'),'updates':upd_count,'cpu':sup.get('cpu_percent'),'memory':sup.get('memory_percent'),'disk':sup.get('disk_used')}
    r=requests.post(cfg['fleet_url'].rstrip('/')+'/api/v1/heartbeat',json=payload,headers={'Authorization':'Bearer '+state['token']},timeout=20); r.raise_for_status()

while True:
    try:
        cfg=loadcfg(); state=enroll(cfg,loadstate())
        if state.get('token'): heartbeat(cfg,state)
    except Exception as e: print('fleet-agent:',repr(e),flush=True)
    time.sleep(max(30,int(loadcfg().get('interval_seconds',60))))
