import unittest,os,sys,io,json,importlib.util,copy
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('cloud_handler',ROOT/'api/index.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
import cloud_auth,cloud_store
class CloudRouteTests(unittest.TestCase):
 def setUp(self):
  self.environment=patch.dict(os.environ,{'GAMEFIT_ADMIN_PASSWORD_HASH':cloud_auth.password_hash('QA-long-password-123'),'GAMEFIT_SESSION_SECRET':'s'*48,'APP_ORIGIN':'https://example.test','GAMEFIT_DEVICE_SYNC_TOKEN':'b'*48});self.environment.start();self.addCleanup(self.environment.stop)
  self.payload={'revision':1,'state':{'staff':[],'attendance':[],'leaves':[],'adjustments':[],'runs':[]},'syncStatus':{'connected':False}}
 def request(self,path,method='GET',body=None,cookie='',token='',origin='https://example.test'):
  h=object.__new__(module.handler);h.path=path;h.command=method;raw=json.dumps(body or {}).encode();h.rfile=io.BytesIO(raw);h.headers={'Host':'example.test','Origin':origin,'Cookie':cookie,'Authorization':token,'Content-Type':'application/json','Content-Length':str(len(raw))};h.client_address=('127.0.0.1',1);result=[];h.send=lambda data,status=200,kind='application/json',headers=None:result.append((status,data,headers));getattr(h,'do_'+method)();return result[0]
 def test_unauthorized_requests_never_read_employee_data(self):
  with patch.object(cloud_store,'read') as read:
   self.assertEqual(self.request('/api/state')[0],401);read.assert_not_called()
 def test_authenticated_origin_and_rewrite(self):
  cookie='gamefit_session='+cloud_auth.session_token()
  with patch.object(cloud_store,'read',return_value=copy.deepcopy(self.payload)):
   status,data,_=self.request('/api?__path=%2Fapi%2Fstate&month=2026-10',cookie=cookie);self.assertEqual(status,200);self.assertTrue(data['cloudMode'])
   self.assertEqual(self.request('/api/state','POST',{'changes':[],'month':'2026-10'},cookie=cookie,origin='https://other.test')[0],403)
 def test_connector_cannot_edit_payroll_or_admin_settings(self):
  token='Bearer '+'b'*48
  with patch.object(cloud_store,'apply') as apply:
   self.assertEqual(self.request('/api/state','POST',{'changes':[]},token=token)[0],401);apply.assert_not_called()
 def test_only_admin_can_enqueue_device_deletion(self):
  cookie='gamefit_session='+cloud_auth.session_token()
  import device_jobs
  with patch.object(device_jobs,'enqueue',return_value={'status':'Queued'}) as enqueue:
   self.assertEqual(self.request('/api/device/users/delete','POST',{},token='Bearer '+'b'*48)[0],401);enqueue.assert_not_called()
   self.assertEqual(self.request('/api/device/users/delete','POST',{},cookie=cookie)[0],200);enqueue.assert_called_once()
if __name__=='__main__':unittest.main()
