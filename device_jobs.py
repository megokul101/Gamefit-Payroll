"""Authenticated admin queues device deletion; connector can only claim existing commands."""
import json,time,secrets,hashlib,hmac
from cloud_store import connect
from device_admin import validate_delete_request,validate_enroll_request,validate_staff_delete

def enqueue(payload):
 action=payload.get('action') or 'delete'
 if action=='enroll':request=validate_enroll_request(payload)
 elif action=='remove':request=validate_staff_delete(payload)
 elif action=='delete':request=validate_delete_request(payload)
 else:raise ValueError('Invalid device command')
 request={**request,'action':action};job=secrets.token_hex(16)
 with connect() as c:
  root=c.execute('SELECT content FROM gamefit_workspace WHERE id=1 FOR UPDATE').fetchone()
  if not root:raise ValueError('Cloud workspace is not initialized')
  staff=next((s for s in root[0].get('staff',[]) if s['id']==request['id']),None)
  if action=='delete' and (not staff or staff.get('deviceUid')!=request['expectedUid'] or staff.get('deviceName','')!=request['expectedName']):raise ValueError('Refresh enrolled users before requesting deletion')
  if action=='enroll' and not staff:raise ValueError('Save the staff profile before enrolling on the device')
  if action=='enroll' and staff.get('status')=='Deleted':raise ValueError('Restore the staff profile before enrolling on the device')
  if action=='remove' and (not staff or staff.get('status')=='Deleted'):raise ValueError('Staff member not found')
  pending=c.execute("SELECT 1 FROM gamefit_device_commands WHERE staff_id=%s AND status IN ('Queued','Executing')",(request['id'],)).fetchone()
  if pending:raise ValueError('This user already has a pending device command')
  c.execute('INSERT INTO gamefit_device_commands(id,staff_id,request,status,created_at) VALUES(%s,%s,%s::jsonb,%s,%s)',(job,request['id'],json.dumps(request),'Queued',time.time()))
  c.execute('UPDATE gamefit_workspace SET revision=revision+1 WHERE id=1')
 message={'enroll':'Enrollment is queued for the terminal connector.','remove':'Terminal removal is queued for the connector.'}.get(action,'Confirmed deletion is queued for the local connector. No device change has occurred yet.')
 return {'id':job,'status':'Queued','message':message}
def list_jobs(c):
 rows=c.execute('SELECT id,staff_id,status,created_at,result FROM gamefit_device_commands ORDER BY created_at DESC LIMIT 30').fetchall()
 return [{'id':r[0],'staffId':r[1],'status':r[2],'createdAt':r[3],'result':r[4]} for r in rows]
def claim():
 with connect() as c:
  now=time.time();expired=c.execute("UPDATE gamefit_device_commands SET status='Expired' WHERE status='Queued' AND created_at<%s",(now-900,)).rowcount;uncertain=c.execute("UPDATE gamefit_device_commands SET status='Uncertain' WHERE status='Executing' AND claimed_at<%s",(now-300,)).rowcount
  rows=c.execute("SELECT id,request FROM gamefit_device_commands WHERE status='Queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED").fetchall();jobs=[]
  for jid,request in rows:
   token=secrets.token_hex(24);c.execute("UPDATE gamefit_device_commands SET status='Executing',claimed_at=%s,claim_hash=%s WHERE id=%s",(now,hashlib.sha256(token.encode()).hexdigest(),jid));jobs.append({'id':jid,'request':request,'claimToken':token})
  if jobs or expired or uncertain:c.execute('UPDATE gamefit_workspace SET revision=revision+1 WHERE id=1')
 return {'jobs':jobs}
def complete(payload):
 status=payload.get('status');message=payload.get('message','');token=payload.get('claimToken','');jid=payload.get('id','')
 device_uid=payload.get('deviceUid',None);device_name=payload.get('deviceName') or ''
 if status not in ['Deleted','Already absent','Failed','Uncertain','Enrolled','Already enrolled'] or not isinstance(message,str) or len(message)>500 or not isinstance(token,str):raise ValueError('Invalid device result')
 if device_uid is not None and (not isinstance(device_uid,int) or not 1<=device_uid<=32767):raise ValueError('Invalid device result')
 if not isinstance(device_name,str) or len(device_name)>160:raise ValueError('Invalid device result')
 with connect() as c:
  row=c.execute('SELECT staff_id,claim_hash,status FROM gamefit_device_commands WHERE id=%s FOR UPDATE',(jid,)).fetchone()
  if not row or row[2]!='Executing' or not hmac.compare_digest(row[1] or '',hashlib.sha256(token.encode()).hexdigest()):raise ValueError('Device command claim is invalid or expired')
  c.execute('UPDATE gamefit_device_commands SET status=%s,result=%s::jsonb,completed_at=%s WHERE id=%s',(status,json.dumps({'message':message}),time.time(),jid))
  if status in ['Deleted','Already absent','Enrolled','Already enrolled']:
   root=c.execute('SELECT content FROM gamefit_workspace WHERE id=1 FOR UPDATE').fetchone();state=root[0]
   for s in state.get('staff',[]):
    if s['id']==row[0]:
     s['deviceEnrolled']=status in ['Enrolled','Already enrolled']
     if device_uid is not None:s['deviceUid']=device_uid
     if device_name:s['deviceName']=device_name
   state.setdefault('staffEvents',[]).append({'id':row[0],'action':'Device enrollment '+status.lower(),'at':time.time(),'job':jid})
   c.execute('UPDATE gamefit_workspace SET content=%s::jsonb,revision=revision+1 WHERE id=1',(json.dumps(state),))
  else:c.execute('UPDATE gamefit_workspace SET revision=revision+1 WHERE id=1')
 return {'status':status}
