"""Narrow, idempotent cloud ingestion: accepts device names and punches, never payroll fields."""
import re,copy
from datetime import datetime
from collections import defaultdict

def validate_batch(payload):
 users=payload.get('users',[]);punches=payload.get('punches',[]);metadata=payload.get('metadata',{})
 if not isinstance(users,list) or len(users)>5000 or not isinstance(punches,list) or len(punches)>1000:raise ValueError('Invalid device batch size')
 cleanusers=[];cleanpunches=[]
 for u in users:
  uid=str(u.get('id',''));name=u.get('name','')
  if not re.fullmatch(r'\d{1,20}',uid) or not isinstance(name,str) or len(name)>160:raise ValueError('Invalid device user')
  internal=u.get('uid')
  if internal is not None and (not isinstance(internal,int) or not 1<=internal<=32767):raise ValueError('Invalid device internal UID')
  cleanusers.append({'id':uid,'name':name.strip(),**({'uid':internal} if internal is not None else {})})
 for p in punches:
  uid=str(p.get('id',''));stamp=p.get('timestamp','')
  if not re.fullmatch(r'\d{1,20}',uid) or not isinstance(stamp,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',stamp):raise ValueError('Invalid device punch')
  datetime.fromisoformat(stamp);cleanpunches.append({'id':uid,'timestamp':stamp})
 meta={'ip':'192.168.1.40','port':4370,'mode':'Read-only local connector'}
 for k in ['users','punches']:
  if k in metadata:
   v=metadata[k]
   if not isinstance(v,int) or not 0<=v<=100000000:raise ValueError('Invalid device totals')
   meta[k]=v
 if 'snapshotComplete' in metadata:meta['snapshotComplete']=bool(metadata['snapshotComplete'])
 return cleanusers,cleanpunches,meta

def merge_device_batch(state,users,punches):
 result=copy.deepcopy(state);staff={s['id']:s for s in result.get('staff',[])}
 if users:
  enrolled={u['id'] for u in users}
  for s in staff.values():s['deviceEnrolled']=s['id'] in enrolled
 for u in users:
  if u['id'] not in staff:staff[u['id']]={'id':u['id'],'name':u['name'] or 'Staff '+u['id'],'section':'Unassigned','role':'Staff','salary':0,'shift':'09:00','end':'18:00','status':'Active','deviceName':u['name']}
  else:staff[u['id']]['deviceName']=u['name']
  staff[u['id']]['deviceEnrolled']=True
  if 'uid' in u:staff[u['id']]['deviceUid']=u['uid']
 records={(a['id'],a['date']):a for a in result.get('attendance',[])}
 grouped=defaultdict(set)
 for p in punches:grouped[(p['id'],p['timestamp'][:10])].add(p['timestamp'][11:])
 for (uid,day),times in grouped.items():
  if uid not in staff:staff[uid]={'id':uid,'name':'Unmapped ID '+uid,'section':'Unassigned','role':'Staff','salary':0,'shift':'09:00','end':'18:00','status':'Archived device ID'}
  previous=records.get((uid,day),{})
  if previous.get('source')=='Manual':continue
  times.update(previous.get('punches',[]));times=sorted(times)
  records[(uid,day)]={'id':uid,'date':day,'in':times[0][:5],'out':times[-1][:5] if len(times)>1 else '', 'status':'Present','source':'eSSL device','punches':times,'review':len(times)==1}
 result['staff']=list(staff.values());result['attendance']=list(records.values());return result
