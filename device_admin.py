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

def device_connection(connect):
 if connect is None:
  from zk import ZK
  connect=lambda:ZK(os.environ.get('GAMEFIT_DEVICE_IP','192.168.1.40'),port=int(os.environ.get('GAMEFIT_DEVICE_PORT','4370')),timeout=15,password=int(os.environ.get('GAMEFIT_COMM_KEY','0')),force_udp=False,ommit_ping=True).connect()
 return connect()
def close_device(conn):
 if conn:
  try:conn.disconnect()
  except Exception:pass
def validate_enroll_request(payload):
 uid=str(payload.get('id',''));name=payload.get('name','')
 if not re.fullmatch(r'\d{1,20}',uid):raise ValueError('Enter a numeric biometric ID')
 if not isinstance(name,str):raise ValueError('Enter a staff name')
 device_name=name.strip()[:24]
 if not device_name:raise ValueError('Enter a staff name the terminal can store')
 return {'id':uid,'name':device_name,'action':'enroll'}
def validate_staff_delete(payload):
 uid=str(payload.get('id',''));confirm=str(payload.get('confirmId',''));reason=payload.get('reason','')
 if not re.fullmatch(r'\d{1,20}',uid) or confirm!=uid or payload.get('acknowledged') is not True:raise ValueError('Type the exact employee ID and acknowledge the enrollment warning')
 if not isinstance(reason,str) or not 3<=len(reason.strip())<=300:raise ValueError('A reason of 3-300 characters is required')
 return {'id':uid,'confirmId':uid,'reason':reason.strip(),'acknowledged':True,'action':'remove'}
def enroll_user(request,connect=None):
 """Create one normal user on the terminal. An existing enrollment is left unchanged so fingerprints are not rewritten."""
 request=validate_enroll_request(request);conn=None;write_started=False
 try:
  conn=device_connection(connect);users=conn.get_users();target=next((u for u in users if str(u.user_id)==request['id']),None)
  if target is not None:return {'status':'Already enrolled','message':'This ID is already on the terminal. The staff profile will use that enrollment.','deviceUid':int(target.uid),'deviceName':target.name.strip() or request['name']}
  used={int(u.uid) for u in users};uid=next((i for i in range(1,32768) if i not in used),None)
  if uid is None:raise ValueError('The terminal has no free user slot')
  write_started=True;conn.set_user(uid=uid,name=request['name'],privilege=0,password='',group_id='',user_id=request['id'],card=0)
  found=next((u for u in conn.get_users() if str(u.user_id)==request['id']),None)
  if found is None:return {'status':'Uncertain','message':'The terminal did not confirm the new user. Sync the device before trying again.'}
  return {'status':'Enrolled','message':'The user was created on the eSSL terminal. Capture fingerprints on the machine.','deviceUid':int(found.uid),'deviceName':found.name.strip() or request['name']}
 except ValueError:
  raise
 except Exception:
  if write_started:return {'status':'Uncertain','message':'Connection was lost while creating the user. Sync the device before trying again.'}
  raise RuntimeError('Device unavailable; the user was not created') from None
 finally:close_device(conn)
def delete_staff_enrollment(request,connect=None):
 """Remove the one terminal user with this employee ID. Other users and attendance logs stay."""
 request=validate_staff_delete(request);conn=None;write_started=False
 try:
  conn=device_connection(connect);users=conn.get_users();target=next((u for u in users if str(u.user_id)==request['id']),None)
  if target is None:return {'status':'Already absent','message':'This ID is not currently enrolled on the device.'}
  admins=[u for u in users if int(getattr(u,'privilege',0))!=0]
  if int(getattr(target,'privilege',0))!=0 and len(admins)<=1:raise ValueError('The last device administrator cannot be deleted')
  write_started=True;conn.delete_user(uid=target.uid)
  if any(str(u.user_id)==request['id'] for u in conn.get_users()):return {'status':'Uncertain','message':'The user still appears enrolled; inspect the terminal before retrying.'}
  return {'status':'Deleted','message':'Removed from the staff directory and the eSSL terminal.'}
 except ValueError:
  if write_started:return {'status':'Uncertain','message':'The device response could not be verified. Inspect the terminal before retrying.'}
  raise
 except Exception:
  if write_started:return {'status':'Uncertain','message':'Connection was lost after sending the delete request. Refresh the enrolled-user list before retrying.'}
  raise RuntimeError('Device unavailable; no delete request was sent') from None
 finally:close_device(conn)
