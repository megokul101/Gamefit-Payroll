"""Vercel entry point. Existing standard-library HTTP application, secured for cloud use."""
import os,sys,json,time,gzip
from pathlib import Path
from urllib.parse import urlparse,parse_qs,urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));os.environ['GAMEFIT_CLOUD']='1'
from server import Handler,merge_changes,validate_terms
from company_profile import validate_company
import cloud_auth,cloud_store
from device_ingest import validate_batch

LOGIN='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Company admin sign in</title><style>body{margin:0;background:#f4f7f2;color:#193c32;font:15px system-ui;display:grid;place-items:center;min-height:100vh}main{background:white;border:1px solid #dce5d8;border-radius:16px;padding:36px;max-width:360px;width:80%}h1{font-size:26px}p{color:#758177;line-height:1.6}input,button{box-sizing:border-box;width:100%;padding:13px;margin-top:15px;border:1px solid #ced8c8;border-radius:7px;font:inherit}button{background:#214b3b;color:white;cursor:pointer}</style><main><h1>Company admin</h1><p>Sign in to manage attendance, payroll and company documents.</p><form action="/api/login" method="post"><label>Admin password<input required type="password" name="password" maxlength="1024" autocomplete="current-password"></label><button>Sign in</button></form></main></html>'''

def validate_root(state):
 validate_terms(state)
 if 'company' in state:state['company']=validate_company(state['company'])

def month_query(path):
 from datetime import datetime,timezone,timedelta
 value=parse_qs(urlparse(path).query).get('month',[datetime.now(timezone(timedelta(hours=5,minutes=30))).strftime('%Y-%m')])[0]
 import re
 if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])',value):raise ValueError('Invalid month')
 return value

class handler(Handler):
 def send(self,data,status=200,kind='application/json',headers=None):
  content=data if isinstance(data,bytes) else data.encode() if isinstance(data,str) else json.dumps(data).encode()
  self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(content)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','same-origin');self.send_header('Content-Security-Policy',"frame-ancestors 'none'")
  for key,value in (headers or {}).items():self.send_header(key,value)
  self.end_headers();self.wfile.write(content)
 def redirect(self,location,headers=None):return self.send('',303,'text/plain',{'Location':location,**(headers or {})})
 def same_origin(self):return self.headers.get('Origin','').rstrip('/')==os.environ.get('APP_ORIGIN','').rstrip('/')
 def allowed(self):return cloud_auth.authorized(self.headers.get('Cookie')) and (self.command!='POST' or self.same_origin())
 def json_body(self,max_size=4*1024*1024):
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON content type required')
  size=int(self.headers.get('Content-Length','0'))
  if not 0<size<=max_size:raise ValueError('Request too large or empty')
  return json.loads(self.rfile.read(size))
 def normalize_route(self):
  parsed=urlparse(self.path);query=parse_qs(parsed.query)
  if '__path' in query:
   original=query.pop('__path')[0]
   if original.startswith('/') and not original.startswith('//'):self.path=original+('?' + urlencode(query,doseq=True) if query else '')
 def do_GET(self):
  self.normalize_route()
  try:
   path=urlparse(self.path).path
   if path=='/health':return self.send({'service':'workforce','configured':cloud_auth.configured()})
   if not cloud_auth.configured():return self.send('Cloud setup is incomplete. Configure admin access, APP_ORIGIN and the database.',503,'text/plain')
   if path=='/login':return self.redirect('/') if cloud_auth.authorized(self.headers.get('Cookie')) else self.send(LOGIN,kind='text/html; charset=utf-8')
   if not self.allowed():return self.redirect('/login') if path=='/' else self.send({'error':'Sign in required'},401)
   if path=='/api/revision':return self.send(cloud_store.revision())
   if path=='/api/state':
    month=month_query(self.path);payload=cloud_store.read(month);return self.send({**payload,'cloudMode':True,'attendanceMonth':month})
   if path=='/api/backup':
    data=gzip.compress(json.dumps(cloud_store.read()['state']).encode());return self.send(data,kind='application/gzip',headers={'Content-Disposition':'attachment; filename="workforce-backup.json.gz"'})
   return super().do_GET()
  except ValueError as e:return self.send({'error':str(e)},400)
  except Exception:return self.send({'error':'Service unavailable. Check database and server configuration.'},503)
 def do_POST(self):
  self.normalize_route()
  try:
   path=urlparse(self.path).path
   if path in ['/api/device-commands/claim','/api/device-commands/complete']:
    if not cloud_auth.bridge_authorized(self.headers.get('Authorization')):return self.send({'error':'Invalid connector credential'},401)
    import device_jobs
    return self.send(device_jobs.claim() if path.endswith('/claim') else device_jobs.complete(self.json_body()))
   if path=='/api/device-ingest':
    if not cloud_auth.bridge_authorized(self.headers.get('Authorization')):return self.send({'error':'Invalid connector credential'},401)
    users,punches,meta=validate_batch(self.json_body());return self.send(cloud_store.ingest(users,punches,meta))
   if not cloud_auth.configured():return self.send({'error':'Cloud setup incomplete'},503)
   if not self.same_origin():return self.send({'error':'Origin rejected'},403)
   if path=='/api/login':
    if not cloud_store.allow_login(self.client_address[0]):return self.send('Too many attempts. Try again in 15 minutes.',429,'text/plain')
    size=int(self.headers.get('Content-Length','0'))
    if not 0<size<=2048:return self.send('Invalid sign-in request',400,'text/plain')
    password=parse_qs(self.rfile.read(size).decode()).get('password',[''])[0]
    if len(password)>1024 or not cloud_auth.verify_password(password):return self.send(LOGIN.replace('<form','<p>Incorrect password.</p><form'),401,'text/html; charset=utf-8')
    token=cloud_auth.session_token();return self.redirect('/',{'Set-Cookie':'gamefit_session='+token+'; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=43200'})
   if not self.allowed():return self.send({'error':'Sign in required'},401)
   if path=='/api/logout':return self.redirect('/login',{'Set-Cookie':'gamefit_session=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0'})
   if path in ['/api/device/users/delete','/api/device/users/enroll','/api/device/users/remove']:
    from device_jobs import enqueue
    body=self.json_body();body.setdefault('action',{'/api/device/users/enroll':'enroll','/api/device/users/remove':'remove'}.get(path,'delete'))
    return self.send(enqueue(body))
   if path=='/api/sync':return self.send({'error':'The local connector pushes device data automatically; cloud hosting cannot poll a private LAN IP directly.'},409)
   if path=='/api/state':
    payload=self.json_body()
    if 'changes' not in payload:raise ValueError('Use a changeset; import backups with the provided migration script')
    cloud_store.apply(payload['changes'],merge_changes,validate_root);month=month_query('/?month='+str(payload.get('month','')))
    result=cloud_store.read(month);return self.send({**result,'cloudMode':True,'attendanceMonth':month})
   return super().do_POST()
  except ValueError as e:return self.send({'error':str(e)},409)
  except Exception:return self.send({'error':'Service unavailable. Check database and server configuration.'},503)
