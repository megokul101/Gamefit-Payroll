"""Postgres state plus individually stored attendance dates for Vercel."""
import os,json,hashlib,time,copy
from datetime import datetime,timezone,timedelta
EMPTY={'staff':[],'attendance':[],'leaves':[],'adjustments':[],'runs':[]}
def connect():
 import psycopg
 dsn=os.environ.get('DATABASE_URL','')
 if not dsn:raise RuntimeError('DATABASE_URL is not configured')
 return psycopg.connect(dsn,connect_timeout=10)
def initialize():
 with connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS gamefit_workspace (id integer PRIMARY KEY, revision bigint NOT NULL DEFAULT 0, content jsonb NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS gamefit_attendance (staff_id text NOT NULL, date text NOT NULL, data jsonb NOT NULL, PRIMARY KEY(staff_id,date))')
  c.execute('CREATE TABLE IF NOT EXISTS gamefit_connector (id integer PRIMARY KEY, seen_at double precision NOT NULL, metadata jsonb NOT NULL)')
  c.execute('CREATE TABLE IF NOT EXISTS gamefit_device_commands (id text PRIMARY KEY, staff_id text NOT NULL, request jsonb NOT NULL, status text NOT NULL, created_at double precision NOT NULL, claimed_at double precision, completed_at double precision, claim_hash text, result jsonb)')
  c.execute('CREATE TABLE IF NOT EXISTS gamefit_login_limits (key text PRIMARY KEY, window_start bigint NOT NULL, attempts integer NOT NULL)')
  root={k:v for k,v in EMPTY.items() if k!='attendance'}
  c.execute('INSERT INTO gamefit_workspace (id,revision,content) VALUES (1,0,%s::jsonb) ON CONFLICT (id) DO NOTHING',(json.dumps(root),))
def connector_status(c):
 row=c.execute('SELECT seen_at,metadata FROM gamefit_connector WHERE id=1').fetchone()
 if not row:return {'connected':False,'lastSuccess':None,'error':'Waiting for the local connector'},None
 seen,meta=row;connected=time.time()-seen<180;stamp=datetime.fromtimestamp(seen,timezone.utc).isoformat()
 return {'connected':connected,'lastSuccess':stamp,'lastAttempt':stamp,'error':None if connected else 'No connector heartbeat for more than 3 minutes'}, {**meta,'syncedAt':stamp}
def read(month=None):
 with connect() as c:
  row=c.execute('SELECT revision,content FROM gamefit_workspace WHERE id=1').fetchone()
  if row is None:raise RuntimeError('Cloud database is not initialized')
  data=c.execute('SELECT data FROM gamefit_attendance'+(' WHERE date LIKE %s' if month else '')+' ORDER BY staff_id,date',((month+'-%',) if month else ())).fetchall()
  state=copy.deepcopy(row[1]);state['attendance']=[r[0] for r in data];status,device=connector_status(c)
  if device:state['device']=device
  from device_jobs import list_jobs
  state['deviceCommands']=list_jobs(c)
 return {'revision':row[0],'state':state,'syncStatus':status}
def revision():
 with connect() as c:
  row=c.execute('SELECT revision FROM gamefit_workspace WHERE id=1').fetchone()
  if row is None:raise RuntimeError('Cloud database is not initialized')
  status,_=connector_status(c)
 return {'revision':row[0],'syncStatus':status,'cloudMode':True}
def write(state,revision):
 """For server-generated document snapshots; attendance is saved via changesets or ingest."""
 root={k:v for k,v in state.items() if k not in ['attendance','device','deviceCommands']}
 with connect() as c:
  row=c.execute('UPDATE gamefit_workspace SET content=%s::jsonb, revision=revision+1 WHERE id=1 AND revision=%s RETURNING revision',(json.dumps(root),revision)).fetchone()
 if row is None:raise ValueError('Workspace changed. Reload before saving again.')
 return row[0]
def apply(changes,merge,validate):
 from state_changes import apply_changes
 with connect() as c:
  row=c.execute('SELECT revision,content FROM gamefit_workspace WHERE id=1 FOR UPDATE').fetchone()
  if not row:raise RuntimeError('Cloud database is not initialized')
  root=copy.deepcopy(row[1]);attendance_changes=[x for x in changes if x.get('key')=='attendance'];other=[x for x in changes if x.get('key')!='attendance']
  nextroot=apply_changes(root,other,merge);validate(nextroot)
  for change in attendance_changes:
   for item in change.get('items',[]):
    base=item.get('base');value=item.get('value');identity=item.get('id','').split('|')
    if len(identity)!=2:raise ValueError('Invalid attendance identity')
    found=c.execute('SELECT data FROM gamefit_attendance WHERE staff_id=%s AND date=%s FOR UPDATE',tuple(identity)).fetchone()
    remote=found[0] if found else None
    temp={'attendance':[remote] if remote else []};updated=apply_changes(temp,[change.__class__(key='attendance',items=[item])],merge)['attendance']
    if updated:c.execute('INSERT INTO gamefit_attendance (staff_id,date,data) VALUES (%s,%s,%s::jsonb) ON CONFLICT(staff_id,date) DO UPDATE SET data=EXCLUDED.data',(identity[0],identity[1],json.dumps(updated[0])))
    else:c.execute('DELETE FROM gamefit_attendance WHERE staff_id=%s AND date=%s',tuple(identity))
  c.execute('UPDATE gamefit_workspace SET content=%s::jsonb, revision=revision+1 WHERE id=1',(json.dumps(nextroot),))
 return row[0]+1

def ingest(users,punches,metadata):
 from device_ingest import merge_device_batch
 # Heartbeats avoid reading the attendance table or changing the workspace revision.
 with connect() as c:
  c.execute('INSERT INTO gamefit_connector(id,seen_at,metadata) VALUES(1,%s,%s::jsonb) ON CONFLICT(id) DO UPDATE SET seen_at=EXCLUDED.seen_at, metadata=gamefit_connector.metadata || EXCLUDED.metadata',(time.time(),json.dumps(metadata)))
  if not users and not punches:return {'accepted':0}
  row=c.execute('SELECT revision,content FROM gamefit_workspace WHERE id=1 FOR UPDATE').fetchone()
  if not row:raise RuntimeError('Cloud database is not initialized')
  keys=sorted({(p['id'],p['timestamp'][:10]) for p in punches})
  old=[]
  if keys:
   placeholders=','.join(['(%s,%s)']*len(keys));params=tuple(v for key in keys for v in key)
   old=[x[0] for x in c.execute('SELECT data FROM gamefit_attendance WHERE (staff_id,date) IN ('+placeholders+')',params).fetchall()]
  state={**copy.deepcopy(row[1]),'attendance':old};updated=merge_device_batch(state,users,punches);records=updated.pop('attendance');changed=updated!=row[1] or records!=old
  if changed:
   with c.cursor() as cursor:cursor.executemany('INSERT INTO gamefit_attendance(staff_id,date,data) VALUES(%s,%s,%s::jsonb) ON CONFLICT(staff_id,date) DO UPDATE SET data=EXCLUDED.data',[(a['id'],a['date'],json.dumps(a)) for a in records])
   c.execute('UPDATE gamefit_workspace SET content=%s::jsonb, revision=revision+1 WHERE id=1',(json.dumps(updated),))
 return {'accepted':len(punches),'changed':changed}
def allow_login(identity):
 key=hashlib.sha256(identity.encode()).hexdigest();window=int(time.time())//900
 with connect() as c:
  row=c.execute('INSERT INTO gamefit_login_limits (key,window_start,attempts) VALUES (%s,%s,1) ON CONFLICT (key) DO UPDATE SET window_start=EXCLUDED.window_start, attempts=CASE WHEN gamefit_login_limits.window_start=EXCLUDED.window_start THEN gamefit_login_limits.attempts+1 ELSE 1 END RETURNING attempts',(key,window)).fetchone()
 return row[0]<=10
