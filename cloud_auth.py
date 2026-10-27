"""Single-admin cloud access with hashed password, signed sessions and separate bridge credentials."""
import os,hashlib,hmac,secrets,time,base64
from http.cookies import SimpleCookie

def configured():return bool(os.environ.get('GAMEFIT_ADMIN_PASSWORD_HASH') and len(os.environ.get('GAMEFIT_SESSION_SECRET',''))>=32 and os.environ.get('APP_ORIGIN','').startswith('https://'))
def password_hash(password,salt=None):
 if len(password)<12:raise ValueError('Choose at least 12 characters')
 salt=salt or secrets.token_hex(16);digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),310000).hex()
 return 'pbkdf2_sha256$310000$'+salt+'$'+digest
def verify_password(password):
 stored=os.environ.get('GAMEFIT_ADMIN_PASSWORD_HASH','')
 try:
  algorithm,rounds,salt,expected=stored.split('$')
  if algorithm!='pbkdf2_sha256' or int(rounds)!=310000:return False
  actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),int(rounds)).hex()
  return hmac.compare_digest(actual,expected)
 except Exception:return False
def session_token():
 fingerprint=hashlib.sha256(os.environ['GAMEFIT_ADMIN_PASSWORD_HASH'].encode()).hexdigest()[:16]
 body=str(int(time.time()))+'.'+secrets.token_hex(16)+'.'+fingerprint
 mac=hmac.new(os.environ['GAMEFIT_SESSION_SECRET'].encode(),body.encode(),hashlib.sha256).hexdigest()
 return body+'.'+mac
def authorized(cookie_header):
 if not configured():return False
 try:
  cookie=SimpleCookie();cookie.load(cookie_header or '');token=cookie['gamefit_session'].value
  issued,nonce,fingerprint,signature=token.split('.')
  if len(nonce)!=32 or not 0<=time.time()-int(issued)<=43200:return False
  expected_fingerprint=hashlib.sha256(os.environ['GAMEFIT_ADMIN_PASSWORD_HASH'].encode()).hexdigest()[:16]
  if not hmac.compare_digest(expected_fingerprint,fingerprint):return False
  body='.'.join([issued,nonce,fingerprint]);expected=hmac.new(os.environ['GAMEFIT_SESSION_SECRET'].encode(),body.encode(),hashlib.sha256).hexdigest()
  return hmac.compare_digest(signature,expected)
 except Exception:return False
def bridge_authorized(header):
 token=os.environ.get('GAMEFIT_DEVICE_SYNC_TOKEN','')
 return len(token)>=32 and hmac.compare_digest(header or '','Bearer '+token)
