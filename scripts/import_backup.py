"""Explicit migration into an EMPTY cloud database. Keeps employee records out of Git."""
import sys,json,gzip
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cloud_store import connect
from server import validate_terms
from company_profile import validate_company
if __name__=='__main__':
 if len(sys.argv)!=2:raise SystemExit('Usage: python scripts/import_backup.py /private/path/workspace.json[.gz]')
 path=Path(sys.argv[1]);raw=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes();state=json.loads(raw)
 if not all(isinstance(state.get(k),list) for k in ['staff','attendance','leaves','adjustments','runs']):raise SystemExit('Not a workforce backup')
 validate_terms(state)
 if 'company' in state:state['company']=validate_company(state['company'])
 attendance=state.pop('attendance');state.pop('device',None)
 with connect() as c:
  row=c.execute('SELECT content FROM gamefit_workspace WHERE id=1 FOR UPDATE').fetchone()
  if not row:raise SystemExit('Run init_cloud_db.py first')
  if row[0].get('staff') or c.execute('SELECT 1 FROM gamefit_attendance LIMIT 1').fetchone():raise SystemExit('Cloud workspace is not empty. Import stopped without overwriting data.')
  c.execute('UPDATE gamefit_workspace SET content=%s::jsonb,revision=revision+1 WHERE id=1',(json.dumps(state),))
  with c.cursor() as cur:cur.executemany('INSERT INTO gamefit_attendance(staff_id,date,data) VALUES(%s,%s,%s::jsonb)',[(a['id'],a['date'],json.dumps(a)) for a in attendance])
 print('Migrated staff, policies, attendance and document history into the empty cloud workspace.')
