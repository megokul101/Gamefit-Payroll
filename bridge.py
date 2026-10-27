#!/usr/bin/env python3
"""Always-on LAN connector. Reads users/logs and sends a narrowly scoped HTTPS payload."""
import os,json,time,argparse,hashlib,tempfile,urllib.request,urllib.error
from pathlib import Path
from datetime import datetime,timedelta
from urllib.parse import urlparse

def local_snapshot(url):
 p=urlparse(url)
 if p.scheme!='http' or p.hostname not in ['127.0.0.1','localhost']:raise ValueError('GAMEFIT_LOCAL_API must point to the local loopback app')
 with urllib.request.urlopen(url.rstrip('/')+'/api/state',timeout=20) as r:state=json.load(r)['state']
 device=state.get('device',{});ids=device.get('enrolledIds')
 if ids is None:raise RuntimeError('Wait for one local device sync before starting the bridge')
 byid={s['id']:s for s in state['staff']};users=[{'id':uid,'name':byid[uid].get('deviceName',byid[uid]['name']),'uid':byid[uid].get('deviceUid')} for uid in ids if uid in byid]
 punches=[{'id':a['id'],'timestamp':a['date']+'T'+(t if len(t)==8 else t+':00')} for a in state['attendance'] if a.get('source')=='eSSL device' for t in a.get('punches',[])]
 return users,punches,{'users':len(ids),'punches':device.get('punches',len(punches))}
def device_snapshot():
 from zk import ZK
 conn=None
 try:
  conn=ZK(os.environ.get('GAMEFIT_DEVICE_IP','192.168.1.40'),port=int(os.environ.get('GAMEFIT_DEVICE_PORT','4370')),timeout=15,password=int(os.environ.get('GAMEFIT_COMM_KEY','0')),force_udp=False,ommit_ping=True).connect()
  users=[{'id':str(u.user_id),'name':u.name.strip(),'uid':int(u.uid)} for u in conn.get_users()]
  logs=conn.get_attendance();punches=[{'id':str(a.user_id),'timestamp':a.timestamp.strftime('%Y-%m-%dT%H:%M:%S')} for a in logs]
  return users,punches,{'users':len(users),'punches':len(logs)}
 finally:
  if conn:
   try:conn.disconnect()
   except Exception:pass

def post(payload,path='/api/device-ingest'):
 origin=os.environ.get('GAMEFIT_CLOUD_URL','').rstrip('/');p=urlparse(origin);token=os.environ.get('GAMEFIT_DEVICE_SYNC_TOKEN','')
 if p.scheme!='https' or not p.hostname or p.username or p.path not in ['', '/'] or p.query or p.fragment:raise ValueError('GAMEFIT_CLOUD_URL must be the HTTPS deployment origin')
 if len(token)<32:raise ValueError('Configure GAMEFIT_DEVICE_SYNC_TOKEN (at least 32 random characters)')
 data=json.dumps(payload).encode();req=urllib.request.Request(origin+path,data=data,headers={'Content-Type':'application/json','Authorization':'Bearer '+token},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
 except urllib.error.HTTPError as e:raise RuntimeError('Cloud rejected the connector request (HTTP '+str(e.code)+')') from None

def process_commands():
 jobs=post({},'/api/device-commands/claim')['jobs']
 for job in jobs:
  try:
   request=job['request'];action=request.get('action','delete');local=os.environ.get('GAMEFIT_LOCAL_API','')
   if local:
    parsed=urlparse(local)
    if parsed.scheme!='http' or parsed.hostname not in ['127.0.0.1','localhost']:raise ValueError('Local API must use the loopback address')
    url=local.rstrip('/')+{'enroll':'/api/device/users/enroll','remove':'/api/device/users/remove'}.get(action,'/api/device/users/delete')
    outgoing=urllib.request.Request(url,data=json.dumps(request).encode(),headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(outgoing,timeout=60) as response:result=json.load(response)
   else:
    if action=='enroll':
     from device_admin import enroll_user
     result=enroll_user(request)
    elif action=='remove':
     from device_admin import delete_staff_enrollment
     result=delete_staff_enrollment(request)
    else:
     from device_admin import delete_enrollment
     result=delete_enrollment(request)
  except Exception as e:result={'status':'Failed','message':str(e)[:400]}
  post({'id':job['id'],'claimToken':job['claimToken'],'status':result['status'],'message':result['message'],'deviceUid':result.get('deviceUid'),'deviceName':result.get('deviceName','')},'/api/device-commands/complete')

def sync_once(full=False):
 process_commands()
 local=os.environ.get('GAMEFIT_LOCAL_API','');users,punches,meta=local_snapshot(local) if local else device_snapshot()
 path=Path(os.environ.get('GAMEFIT_BRIDGE_STATE',str(Path(__file__).with_name('bridge-state.json'))))
 previous=json.loads(path.read_text()) if path.exists() else {};seen=set(previous.get('recent',[]));high=previous.get('high','');cutoff=(datetime.now()-timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S')
 unique={(p['id'],p['timestamp']):p for p in punches};punches=sorted(unique.values(),key=lambda p:(p['timestamp'],p['id']))
 digest=hashlib.sha256(json.dumps(sorted(users,key=lambda u:u['id']),sort_keys=True).encode()).hexdigest()
 pending=punches if full or not high else [p for p in punches if p['timestamp']>high or (p['timestamp']>=cutoff and p['id']+'|'+p['timestamp'] not in seen)]
 newusers=users if full or digest!=previous.get('usersDigest') else []
 if newusers:post({'users':newusers,'punches':[],'metadata':{**meta,'snapshotComplete':False}})
 for offset in range(0,len(pending),1000):post({'users':[],'punches':pending[offset:offset+1000],'metadata':{**meta,'snapshotComplete':False}})
 post({'users':[],'punches':[],'metadata':{**meta,'snapshotComplete':True}})
 nextstate={'high':punches[-1]['timestamp'] if punches else high,'usersDigest':digest,'recent':[p['id']+'|'+p['timestamp'] for p in punches if p['timestamp']>=cutoff]}
 path.parent.mkdir(parents=True,exist_ok=True);fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.bridge-')
 try:
  with os.fdopen(fd,'w') as f:json.dump(nextstate,f)
  os.chmod(temp,0o600);os.replace(temp,path)
 finally:
  if os.path.exists(temp):os.unlink(temp)
 return {'users':len(users),'newPunches':len(pending),'totalDevicePunches':meta['punches']}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');parser.add_argument('--full',action='store_true');args=parser.parse_args()
 while True:
  started=time.monotonic()
  try:print(json.dumps({'syncedAt':datetime.now().astimezone().isoformat(),**sync_once(args.full)}),flush=True)
  except Exception as e:print('Connector unavailable: '+str(e),flush=True)
  if args.once:break
  args.full=False;time.sleep(max(1,max(15,int(os.environ.get('GAMEFIT_SYNC_INTERVAL','60')))-(time.monotonic()-started)))
