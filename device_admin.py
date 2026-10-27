"""Explicit, individually confirmed device operations. No bulk deletion or enrollment backups."""
import re,os

def validate_delete_request(payload):
 uid=str(payload.get('id',''));confirm=str(payload.get('confirmId',''));reason=payload.get('reason','');expected=payload.get('expectedUid');name=payload.get('expectedName','')
 if not re.fullmatch(r'\d{1,20}',uid) or confirm!=uid or payload.get('acknowledged') is not True:raise ValueError('Type the exact employee ID and acknowledge the enrollment warning')
 if not isinstance(expected,int) or not 1<=expected<=32767:raise ValueError('Refresh device users before deleting this enrollment')
 if not isinstance(reason,str) or not 3<=len(reason.strip())<=300:raise ValueError('A reason of 3-300 characters is required')
 if not isinstance(name,str) or len(name)>160:raise ValueError('Invalid expected device name')
 return {'id':uid,'confirmId':uid,'reason':reason.strip(),'expectedUid':expected,'expectedName':name,'acknowledged':True}

def delete_enrollment(request,connect=None):
 request=validate_delete_request(request);conn=None;write_started=False
 if connect is None:
  from zk import ZK
  connect=lambda:ZK(os.environ.get('GAMEFIT_DEVICE_IP','192.168.1.40'),port=int(os.environ.get('GAMEFIT_DEVICE_PORT','4370')),timeout=15,password=int(os.environ.get('GAMEFIT_COMM_KEY','0')),force_udp=False,ommit_ping=True).connect()
 try:
  conn=connect();users=conn.get_users();target=next((u for u in users if str(u.user_id)==request['id']),None)
  if target is None:return {'status':'Already absent','message':'This ID is not currently enrolled on the device.'}
  if int(target.uid)!=request['expectedUid'] or target.name.strip()!=request['expectedName']:raise ValueError('The enrolled user changed. Refresh and confirm again.')
  admins=[u for u in users if int(getattr(u,'privilege',0))!=0]
  if int(getattr(target,'privilege',0))!=0 and len(admins)<=1:raise ValueError('The last device administrator cannot be deleted')
  write_started=True;conn.delete_user(uid=target.uid)
  remaining=conn.get_users()
  if any(str(u.user_id)==request['id'] for u in remaining):return {'status':'Uncertain','message':'The user still appears enrolled; inspect the terminal before retrying.'}
  return {'status':'Deleted','message':'The specified device enrollment was deleted and absence verified.'}
 except ValueError:
  if write_started:return {'status':'Uncertain','message':'The device response could not be verified. Inspect the terminal before retrying.'}
  raise
 except Exception:
  if write_started:return {'status':'Uncertain','message':'Connection was lost after sending the delete request. Refresh the enrolled-user list before retrying.'}
  raise RuntimeError('Device unavailable; no delete request was sent') from None
 finally:
  if conn:
   try:conn.disconnect()
   except Exception:pass
