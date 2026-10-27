"""Small optimistic changesets; large attendance histories are never posted for a profile edit."""
import copy,json
KEYS={'staff':('id',),'attendance':('id','date'),'monthlyTerms':('id','month'),'dayOverrides':('id','date'),'staffEvents':None}
PROTECTED={'device','connector','payslips','deviceCommands','_loadedMonth'}
def identity(row,fields):return '|'.join(str(row.get(k,'')) for k in fields)
def apply_value(base,value,remote,merge):
 if remote==base:return copy.deepcopy(value)
 if value==base or value==remote:return copy.deepcopy(remote)
 return merge(base,value,remote)
def apply_changes(state,changes,merge,allow_protected=False):
 if not isinstance(changes,list) or len(changes)>100:raise ValueError('Invalid changeset')
 out=copy.deepcopy(state)
 for change in changes:
  key=change.get('key')
  if not isinstance(key,str) or key.startswith('_') or (key in PROTECTED and not allow_protected):raise ValueError('This field cannot be changed directly')
  if 'items' in change:
   fields=KEYS.get(key)
   if not fields:raise ValueError('Invalid item collection')
   current={identity(x,fields):x for x in out.get(key,[])}
   for item in change['items']:
    ident=item['id'];base=item.get('base');value=item.get('value');remote=current.get(ident)
    if value is None:
     if remote!=base:raise ValueError('Another update changed this record')
     current.pop(ident,None)
    else:
     if identity(value,fields)!=ident:raise ValueError('Record identity changed')
     current[ident]=apply_value(base,value,remote,merge)
   out[key]=list(current.values())
  else:
   base=change.get('base');value=change.get('value');out[key]=apply_value(base,value,out.get(key),merge)
 return out
