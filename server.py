#!/usr/bin/env python3
"""Gamefit local app. Attendance logs are read from the terminal. Staff add and delete also update that one enrollment."""
import json, os, sqlite3, threading, time, csv, io, uuid, re
from urllib.parse import urlparse,parse_qs
from payroll_engine import calculate_month,payslip_pdf
from company_profile import company_for,validate_company
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from collections import defaultdict
ROOT=Path(__file__).resolve().parent
DB=ROOT/'data'/'gamefit.sqlite3'
CLOUD=os.environ.get('GAMEFIT_CLOUD')=='1'
if not CLOUD:DB.parent.mkdir(exist_ok=True)
LOCK=threading.RLock()
SYNC=threading.Lock()
SYNC_STATUS={'connected':False,'lastAttempt':None,'lastSuccess':None,'error':None}
PORT=int(os.environ.get('GAMEFIT_PORT','8780'))
EMPTY={'staff':[],'attendance':[],'leaves':[],'adjustments':[],'runs':[]}
def db():
 c=sqlite3.connect(DB); c.execute('CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, content TEXT NOT NULL)');c.execute('INSERT OR IGNORE INTO workspace VALUES (1,0,?)',(json.dumps(EMPTY),));c.commit();return c
def read(month=None):
 if CLOUD:
  import cloud_store
  return cloud_store.read(month)
 with db() as c:
  rev,content=c.execute('SELECT revision,content FROM workspace WHERE id=1').fetchone()
 return {'revision':rev,'state':json.loads(content)}
def write(s,rev):
 if CLOUD:
  import cloud_store
  return cloud_store.write(s,rev)
 with db() as c:
  c.execute('UPDATE workspace SET revision=revision+1,content=? WHERE id=1 AND revision=?',(json.dumps(s),rev))
  if not c.total_changes: raise ValueError('Workspace changed. Reload before saving again.')
 return rev+1
def sync_device():
 if not SYNC.acquire(False): raise ValueError('A device sync is already running')
 conn=None
 try:
  from zk import ZK
  conn=ZK('192.168.1.40',port=4370,timeout=15,password=int(os.environ.get('GAMEFIT_COMM_KEY','0')),force_udp=False,ommit_ping=True).connect()
  users=conn.get_users(); logs=conn.get_attendance()
  grouped=defaultdict(set)
  for a in logs:grouped[(str(a.user_id),a.timestamp.strftime('%Y-%m-%d'))].add(a.timestamp.strftime('%H:%M:%S'))
  with LOCK:
   payload=read();s=payload['state'];byid={x['id']:x for x in s['staff']}
   for u in users:
    uid=str(u.user_id)
    if uid not in byid:
     byid[uid]={'id':uid,'name':u.name.strip() or 'Staff '+uid,'section':'Unassigned','role':'Staff','salary':0,'shift':'09:00','status':'Active','deviceName':u.name.strip()}
    else:byid[uid]['deviceName']=u.name.strip()
   old={(a['id'],a['date']):a for a in s['attendance']}
   for (uid,date),times in grouped.items():
    if uid not in byid:byid[uid]={'id':uid,'name':'Unmapped ID '+uid,'section':'Unassigned','role':'Staff','salary':0,'shift':'09:00','status':'Archived device ID'}
    if old.get((uid,date),{}).get('source')=='Manual':continue
    tt=sorted(times)
    old[(uid,date)]={'id':uid,'date':date,'in':tt[0][:5],'out':tt[-1][:5] if len(tt)>1 else '', 'status':'Present','source':'eSSL device','punches':tt,'review':len(tt)==1}
   enrolled_ids={str(u.user_id) for u in users}
   internal_ids={str(u.user_id):int(u.uid) for u in users}
   for member in byid.values():
    member['deviceEnrolled']=member['id'] in enrolled_ids
    if member['id'] in internal_ids:member['deviceUid']=internal_ids[member['id']]
   s['staff']=list(byid.values());s['attendance']=list(old.values())
   s['device']={'ip':'192.168.1.40','port':4370,'users':len(users),'enrolledIds':[str(u.user_id) for u in users],'punches':len(logs),'syncedAt':datetime.now().astimezone().isoformat(),'mode':'Read only · first / last punch'}
   rev=write(s,payload['revision'])
   SYNC_STATUS.update(connected=True,lastAttempt=s['device']['syncedAt'],lastSuccess=s['device']['syncedAt'],error=None)
   return {'revision':rev,'state':s}
 except Exception as e:
  SYNC_STATUS.update(connected=False,lastAttempt=datetime.now().astimezone().isoformat(),error=str(e))
  raise
 finally:
  if conn:
   try:conn.disconnect()
   except Exception:pass
  SYNC.release()
def background_sync():
 while True:
  try:
   with LOCK:enabled=read()['state'].get('autoSync',False)
   if enabled:sync_device()
  except Exception as e:print('Sync unavailable: '+str(e),flush=True)
  time.sleep(60)

def merge_changes(base,local,remote):
 if local==base:return remote
 if remote==base or local==remote:return local
 if isinstance(base,dict) and isinstance(local,dict) and isinstance(remote,dict):
  out=dict(remote)
  for key in set(base)|set(local):
   if key not in local:
    if remote.get(key)!=base.get(key):raise ValueError('Concurrent change to '+key)
    out.pop(key,None)
   elif key not in base:
    if key in remote and remote[key]!=local[key]:raise ValueError('Concurrent new field '+key)
    out[key]=local[key]
   elif key in remote:out[key]=merge_changes(base[key],local[key],remote[key])
   else:
    if local[key]!=base[key]:raise ValueError('Concurrent deletion of '+key)
  return out
 if isinstance(base,list) and isinstance(local,list) and isinstance(remote,list):
  allrows=base+local+remote
  if allrows and all(isinstance(x,dict) and 'id' in x for x in allrows):
   def identity(x):return str(x['id'])+'|'+str(x.get('date',x.get('month','')))
   maps=[{identity(x):x for x in arr} for arr in [base,local,remote]]
   if all(len(m)==len(arr) for m,arr in zip(maps,[base,local,remote])):
    return list(merge_changes(*maps).values())
 raise ValueError('Another edit changed the same records. Back up your changes and reload.')
def record_device_result(request,result):
 with LOCK:
  current=read();state=current['state']
  state.setdefault('staffEvents',[]).append({'id':request['id'],'action':'Device '+result['status'],'at':datetime.now().astimezone().isoformat(),'reason':request.get('reason','')})
  if result['status'] in ['Deleted','Already absent']:
   for member in state['staff']:
    if member['id']==request['id']:member['deviceEnrolled']=False
   if state.get('device') and 'enrolledIds' in state['device']:state['device']['enrolledIds']=[x for x in state['device']['enrolledIds'] if x!=request['id']]
  if result['status'] in ['Enrolled','Already enrolled']:
   for member in state['staff']:
    if member['id']==request['id']:
     member['deviceEnrolled']=True
     if result.get('deviceUid') is not None:member['deviceUid']=result['deviceUid']
     if result.get('deviceName'):member['deviceName']=result['deviceName']
   if state.get('device') and 'enrolledIds' in state['device'] and request['id'] not in state['device']['enrolledIds']:state['device']['enrolledIds'].append(request['id'])
  rev=write(state,current['revision'])
 return {**result,'revision':rev,'state':state}
def run_device_operation(operation,request):
 if not SYNC.acquire(timeout=20):raise ValueError('Device is busy; try again after sync finishes')
 try:return record_device_result(request,operation(request))
 finally:SYNC.release()
def validate_terms(state):
 for t in state.get('monthlyTerms',[]):
  if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',t.get('month','')):raise ValueError('Invalid policy month')
  for key,low,high in [('salary',0,100000000),('dailyHours',.25,24),('halfHours',0,24),('breakMinutes',0,720),('paidLeaveDays',0,31),('weeklyOffDays',0,31),('fixedDivisor',1,31),('lateGraceMinutes',0,240)]:
   value=float(t.get(key,0))
   if not low<=value<=high:raise ValueError('Invalid policy field '+key)
  if float(t['halfHours'])>float(t['dailyHours']):raise ValueError('Half-day hours exceed full-day hours')
  if len(set(t.get('weeklyOffDates',[])))>int(t['weeklyOffDays']):raise ValueError('Too many paid weekly-off dates')
  for d in t.get('weeklyOffDates',[]):
   if not d.startswith(t['month']+'-'):raise ValueError('Weekly-off date is outside policy month')
   datetime.fromisoformat(d)

class Handler(BaseHTTPRequestHandler):
 def allowed(self):
  hosts=[f'127.0.0.1:{PORT}',f'localhost:{PORT}']
  return self.headers.get('Host') in hosts and self.headers.get('Origin',f'http://127.0.0.1:{PORT}') in ['http://'+h for h in hosts]
 def send(self,data,status=200,kind='application/json'):
  content=data if isinstance(data,bytes) else data.encode() if isinstance(data,str) else json.dumps(data).encode()
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Security-Policy',"frame-ancestors 'none'");self.end_headers();self.wfile.write(content)
 def do_GET(self):
  if not self.allowed():return self.send({'error':'Origin rejected'},403)
  parsed=urlparse(self.path);query=parse_qs(parsed.query)
  if parsed.path in ['/api/payroll','/api/payslip']:
   try:
    month=query.get('month',[''])[0]
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):raise ValueError('Invalid month')
    with LOCK:payload=read(month=month)
    calculated=calculate_month(payload['state'],month)
    if parsed.path=='/api/payroll':return self.send({**calculated,'revision':payload['revision']})
    issued=None;uid=query.get('id',[''])[0];reference=query.get('reference',[''])[0]
    if reference:
     issued=next((p for p in payload['state'].get('payslips',[]) if p['reference']==reference),None)
     if not issued:raise ValueError('Payslip not found')
     row=issued['row'];month=issued['month']
    else:row=next((r for r in calculated['rows'] if r['id']==uid),None)
    if not row:raise ValueError('Staff member not found')
    return self.send(payslip_pdf(row,month,issued,company_for(payload['state']) if not issued else issued.get('company',None)),kind='application/pdf')
   except Exception as e:return self.send({'error':str(e)},400)
  if self.path=='/':return self.send((ROOT/'index.html').read_text(),kind='text/html; charset=utf-8')
  if self.path=='/api/revision':
   with LOCK:
    payload=read();return self.send({'revision':payload['revision'],'syncStatus':dict(SYNC_STATUS),'cloudMode':False})
  if self.path=='/api/state':
   with LOCK:
    payload=read();payload['syncStatus']=dict(SYNC_STATUS);payload['cloudMode']=False;return self.send(payload)
  return self.send({'error':'Not found'},404)
 def do_POST(self):
  if not self.allowed() or self.headers.get('Content-Type')!='application/json':return self.send({'error':'Origin or content type rejected'},403)
  try:
   if self.path in ['/api/device/users/delete','/api/device/users/enroll','/api/device/users/remove']:
    from device_admin import validate_delete_request,delete_enrollment,validate_enroll_request,enroll_user,validate_staff_delete,delete_staff_enrollment
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=10000:raise ValueError('Invalid device request')
    payload=json.loads(self.rfile.read(size))
    if self.path.endswith('/enroll'):operation,request=enroll_user,validate_enroll_request(payload)
    elif self.path.endswith('/remove'):operation,request=delete_staff_enrollment,validate_staff_delete(payload)
    else:operation,request=delete_enrollment,validate_delete_request(payload)
    return self.send(run_device_operation(operation,request))
   if self.path=='/api/sync':return self.send(sync_device())
   if self.path=='/api/issue-payslip':
    size=int(self.headers.get('Content-Length','0'))
    if size>10000:raise ValueError('Request too large')
    request=json.loads(self.rfile.read(size));month=request['month']
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',month):raise ValueError('Invalid month')
    with LOCK:
     payload=read(month=month);state=payload['state'];calculated=calculate_month(state,month)
     row=next((r for r in calculated['rows'] if r['id']==request['id']),None)
     if not row:raise ValueError('Staff member not found')
     if not row['configured'] or row['salary']<=0:raise ValueError('Configure a positive salary and monthly policy first')
     if row['reviewDays'] or row['pendingDays']:raise ValueError('Resolve review days and wait for the pay month to finish. A draft PDF is available now.')
     if row['net']<0:raise ValueError('Net pay is negative; review deductions first')
     existing=next((p for p in state.get('payslips',[]) if p['id']==row['id'] and p['month']==month),None)
     if existing:raise ValueError('A payslip is already issued for this person and month; use the saved PDF')
     slip={'reference':company_for(state)['payslipPrefix']+'-'+month.replace('-','')+'-'+uuid.uuid4().hex[:8].upper(),'id':row['id'],'month':month,'issuedAt':datetime.now().astimezone().isoformat(),'row':row,'company':company_for(state)}
     state.setdefault('payslips',[]).append(slip);rev=write(state,payload['revision'])
    return self.send({'reference':slip['reference'],'revision':rev,'state':state})
   if self.path=='/api/state':
    size=int(self.headers.get('Content-Length','0'))
    if size>20000000:raise ValueError('Workspace too large')
    payload=json.loads(self.rfile.read(size))
    with LOCK:
     latest=read()
     if 'changes' in payload:
      from state_changes import apply_changes
      s=apply_changes(latest['state'],payload['changes'],merge_changes)
     else:
      s=payload['state']
     if not all(isinstance(s.get(k),list) for k in EMPTY):raise ValueError('Invalid workspace')
     if 'changes' not in payload and int(payload['revision'])!=latest['revision']:
      if not isinstance(payload.get('baseState'),dict):raise ValueError('Workspace changed; reload before saving')
      s=merge_changes(payload['baseState'],s,latest['state'])
     validate_terms(s)
     if 'company' in s:s['company']=validate_company(s['company'])
     rev=write(s,latest['revision'])
    return self.send({'revision':rev,'state':s})
   return self.send({'error':'Not found'},404)
  except Exception as e:return self.send({'error':str(e)},409 if isinstance(e,ValueError) else 502)
 def log_message(self,*args):pass
if __name__=='__main__':
 db()
 threading.Thread(target=background_sync,daemon=True).start()
 print(f'Gamefit running at http://127.0.0.1:{PORT} (this Mac only)',flush=True)
 ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
