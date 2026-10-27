import sys,getpass
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cloud_auth import password_hash
if __name__=='__main__':
 p=getpass.getpass('New admin password (12+ characters): ')
 if p!=getpass.getpass('Confirm password: '):raise SystemExit('Passwords did not match')
 print('GAMEFIT_ADMIN_PASSWORD_HASH='+password_hash(p))
