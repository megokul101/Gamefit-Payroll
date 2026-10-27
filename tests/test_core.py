import unittest,sys,os,io,json,copy,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from state_changes import apply_changes
from device_ingest import validate_batch,merge_device_batch
from company_profile import validate_company
from cloud_auth import password_hash,verify_password,session_token,authorized,bridge_authorized
from server import merge_changes
from payroll_engine import calculate_month

class CoreTests(unittest.TestCase):
 def test_company_limits_and_logo(self):
  c=validate_company({'name':'QA & Company','address':'Sample address','payslipPrefix':'QA'})
  self.assertEqual(c['name'],'QA & Company')
  for value in [{'name':''},{'name':'QA','logo':'data:image/svg+xml;base64,PHN2Zz4='},{'name':'QA','payslipPrefix':'<script>'}]:
   with self.assertRaises(ValueError):validate_company(value)
 def test_admin_sessions(self):
  env={'GAMEFIT_ADMIN_PASSWORD_HASH':password_hash('QA-long-password-123'),'GAMEFIT_SESSION_SECRET':'s'*48,'APP_ORIGIN':'https://example.test','GAMEFIT_DEVICE_SYNC_TOKEN':'b'*48}
  with patch.dict(os.environ,env):
   self.assertTrue(verify_password('QA-long-password-123'));self.assertFalse(verify_password('wrong'))
   token=session_token();self.assertTrue(authorized('gamefit_session='+token));self.assertFalse(authorized('gamefit_session='+token[:-1]+'x'))
   self.assertTrue(bridge_authorized('Bearer '+'b'*48));self.assertFalse(bridge_authorized('Bearer '+'s'*48))
   with patch.dict(os.environ,{'GAMEFIT_ADMIN_PASSWORD_HASH':password_hash('Other-password-123')}):self.assertFalse(authorized('gamefit_session='+token))
 def test_changes_preserve_sync(self):
  root={'staff':[{'id':'1','name':'QA','salary':0,'deviceName':'Old'}],'attendance':[{'id':'1','date':'2026-10-01','in':'09:00','out':'18:00'}]}
  changes=[{'key':'staff','items':[{'id':'1','base':{'id':'1','name':'QA','salary':0,'deviceName':'Old'},'value':{'id':'1','name':'QA','salary':30000,'deviceName':'Old'}}]}]
  root['staff'][0]['deviceName']='New';result=apply_changes(root,changes,merge_changes)
  self.assertEqual(result['staff'][0]['salary'],30000);self.assertEqual(result['staff'][0]['deviceName'],'New');self.assertEqual(len(result['attendance']),1)
  with self.assertRaises(ValueError):apply_changes(root,[{'key':'payslips','value':[]}],merge_changes)
 def test_ingest_scope_duplicates_and_deleted_users(self):
  root={'staff':[{'id':'1','name':'Chosen name','salary':30000,'status':'Deleted'}],'attendance':[],'monthlyTerms':[{'id':'1','month':'2026-10','salary':30000}]}
  users,punches,meta=validate_batch({'users':[{'id':'1','name':'Device name','salary':999999}],'punches':[{'id':'1','timestamp':'2026-10-01T09:00:00'},{'id':'1','timestamp':'2026-10-01T18:00:00'}],'metadata':{'users':1,'punches':2}})
  updated=merge_device_batch(root,users,punches);again=merge_device_batch(updated,users,punches)
  self.assertEqual(updated,again);self.assertEqual(updated['staff'][0]['status'],'Deleted');self.assertEqual(updated['staff'][0]['salary'],30000);self.assertEqual(updated['staff'][0]['name'],'Chosen name');self.assertEqual(updated['attendance'][0]['out'],'18:00')
  updated['attendance'][0].update(source='Manual',out='17:00');self.assertEqual(merge_device_batch(updated,users,punches)['attendance'][0]['out'],'17:00')
 def test_duty_rules_and_end_date(self):
  s={'staff':[{'id':'1','name':'QA','salary':31000,'employmentEndDate':'2026-10-15'}],'monthlyTerms':[{'id':'1','month':'2026-10','salary':31000,'dailyHours':8,'halfHours':4,'autoAbsent':False,'shortHours':True}],'attendance':[{'id':'1','date':'2026-10-01','status':'Present','in':'09:00','out':'13:00'}]}
  r=calculate_month(s,'2026-10',datetime(2026,11,1,tzinfo=timezone(timedelta(hours=5,minutes=30))))['rows'][0]
  self.assertEqual(r['gross'],15000);self.assertEqual(r['days'][0]['status'],'Half day');self.assertEqual(r['lop'],500);self.assertEqual(r['days'][3]['weekday'],'Sunday')
if __name__=='__main__':unittest.main()

class DeviceDeletionTests(unittest.TestCase):
 def test_exact_user_only_and_verification(self):
  from device_admin import delete_enrollment
  from types import SimpleNamespace
  class FakeDevice:
   def __init__(self):self.users=[SimpleNamespace(user_id='10',uid=2,name='QA target',privilege=0),SimpleNamespace(user_id='20',uid=3,name='QA other',privilege=0)];self.deleted=[]
   def get_users(self):return list(self.users)
   def delete_user(self,uid):self.deleted.append(uid);self.users=[u for u in self.users if u.uid!=uid]
   def disconnect(self):pass
  device=FakeDevice();request={'id':'10','confirmId':'10','expectedUid':2,'expectedName':'QA target','reason':'QA confirmed operation','acknowledged':True}
  result=delete_enrollment(request,lambda:device)
  self.assertEqual(result['status'],'Deleted');self.assertEqual(device.deleted,[2]);self.assertEqual([u.user_id for u in device.users],['20'])
 def test_confirmation_and_last_admin(self):
  from device_admin import delete_enrollment
  from types import SimpleNamespace
  request={'id':'1','confirmId':'wrong','expectedUid':1,'expectedName':'QA admin','reason':'QA operation','acknowledged':True}
  with self.assertRaises(ValueError):delete_enrollment(request,lambda:None)
  class FakeAdmin:
   def get_users(self):return [SimpleNamespace(user_id='1',uid=1,name='QA admin',privilege=14)]
   def delete_user(self,uid):raise AssertionError('The last administrator must never reach the delete method')
   def disconnect(self):pass
  request['confirmId']='1'
  with self.assertRaises(ValueError):delete_enrollment(request,lambda:FakeAdmin())
 def test_enroll_creates_one_user_and_leaves_existing_fingerprints(self):
  from device_admin import enroll_user
  from types import SimpleNamespace
  class FakeDevice:
   def __init__(self):self.users=[SimpleNamespace(user_id='20',uid=3,name='QA other',privilege=0)];self.created=[]
   def get_users(self):return list(self.users)
   def set_user(self,uid=None,name='',privilege=0,password='',group_id='',user_id='',card=0):self.created.append(user_id);self.users.append(SimpleNamespace(user_id=str(user_id),uid=uid,name=name,privilege=privilege))
   def disconnect(self):pass
  device=FakeDevice()
  created=enroll_user({'id':'10','name':'QA target'},lambda:device)
  self.assertEqual(created['status'],'Enrolled');self.assertEqual(created['deviceUid'],1);self.assertEqual(device.created,['10'])
  linked=enroll_user({'id':'20','name':'Different name'},lambda:device)
  self.assertEqual(linked['status'],'Already enrolled');self.assertEqual(device.created,['10']);self.assertEqual(device.users[0].name,'QA other')
 def test_staff_delete_removes_only_that_terminal_user(self):
  from device_admin import delete_staff_enrollment
  from types import SimpleNamespace
  class FakeDevice:
   def __init__(self):self.users=[SimpleNamespace(user_id='10',uid=2,name='QA target',privilege=0),SimpleNamespace(user_id='20',uid=3,name='QA other',privilege=0)];self.deleted=[]
   def get_users(self):return list(self.users)
   def delete_user(self,uid):self.deleted.append(uid);self.users=[u for u in self.users if u.uid!=uid]
   def disconnect(self):pass
  device=FakeDevice();request={'id':'10','confirmId':'10','reason':'Left the company','acknowledged':True}
  result=delete_staff_enrollment(request,lambda:device)
  self.assertEqual(result['status'],'Deleted');self.assertEqual(device.deleted,[2]);self.assertEqual([u.user_id for u in device.users],['20'])
  absent=delete_staff_enrollment(request,lambda:device)
  self.assertEqual(absent['status'],'Already absent')
  with self.assertRaises(ValueError):delete_staff_enrollment({**request,'confirmId':'11'},lambda:device)
