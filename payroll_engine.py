"""Explicit monthly attendance policy and payroll calculation; no statutory tax assumptions."""
import calendar,math
from datetime import date,datetime,timedelta,timezone
IST=timezone(timedelta(hours=5,minutes=30))
DEFAULT={'dailyHours':8,'breakMinutes':0,'halfHours':4,'paidLeaveDays':0,'weeklyOffDays':0,'weeklyOffDates':[], 'autoAbsent':False,'shortHours':False,'lateGraceMinutes':0,'divisor':'calendar','fixedDivisor':30}
def dates_in_month(month):
 year,mon=map(int,month.split('-'));return [date(year,mon,i).isoformat() for i in range(1,calendar.monthrange(year,mon)[1]+1)]
def terms_for(state,staff,month):
 matches=[t for t in state.get('monthlyTerms',[]) if t['id']==staff['id'] and t['month']<=month]
 saved=max(matches,key=lambda t:t['month']) if matches else None
 result={**DEFAULT,'salary':staff.get('salary',0),'shift':staff.get('shift','09:00'),'end':staff.get('end','18:00'), 'effectiveFrom':saved.get('effectiveFrom',saved['month']+'-01') if saved else month+'-01',**(saved or {}),'configured':bool(saved)}
 # Off dates are specific to one month; a recurring weekday may generate the next month's dates.
 if saved and saved['month']!=month:
  result['weeklyOffDates']=[]
  if saved.get('weeklyDay','')!='':result['weeklyOffDates']=weekday_offs(month,int(saved['weeklyDay']),int(result['weeklyOffDays']))
 return result
def weekday_offs(month,weekday,count):
 return [d for d in dates_in_month(month) if (date.fromisoformat(d).weekday()+1)%7==weekday][:count]
def minutes(t):
 if not t:return None
 p=t.split(':');return int(p[0])*60+int(p[1])
def amount(value):return math.floor(float(value)*100+0.5)/100

def calculate_month(state,month,now=None):
 days=dates_in_month(month);now=now or datetime.now(IST)
 if now.tzinfo is None:now=now.replace(tzinfo=IST)
 now=now.astimezone(IST);today=now.date().isoformat()
 att={(a['id'],a['date']):a for a in state.get('attendance',[])}
 overrides={(a['id'],a['date']):a for a in state.get('dayOverrides',[])}
 rows=[]
 for staff in state.get('staff',[]):
  uid=staff['id'];t=terms_for(state,staff,month)
  offdates=set(t.get('weeklyOffDates',[]));paid_used=0;off_used=0;details=[]
  for d in days:
   a=att.get((uid,d),{});o=overrides.get((uid,d));leave=next((l for l in state.get('leaves',[]) if l['id']==uid and l['status']=='Approved' and l['start']<=d<=l['end']),None)
   status='Unrecorded';lop=0.;credit=0.;review=False;note='';hours=None;late_minutes=0;early_minutes=0;closed=d<today
   end=minutes(t.get('end','18:00'));start=minutes(t.get('shift','09:00'))
   overnight=end<=start
   if d==today and not overnight:closed=now.hour*60+now.minute>=end
   if overnight and d<today:closed=datetime.fromisoformat(d+'T'+t.get('end','18:00')).replace(tzinfo=IST)+timedelta(days=1)<=now
   effective=max(t.get('effectiveFrom',month+'-01'),staff.get('joinDate') or '0001-01-01')<=d<=(staff.get('employmentEndDate') or '9999-12-31')
   pending=d>today or not closed
   rawtype=o.get('type') if o else None
   if not rawtype and d in offdates:rawtype='Weekly off'
   if not rawtype and leave:rawtype='Paid leave' if leave['type']=='Paid' else 'Unpaid leave'
   if not rawtype and a.get('status')=='Leave':rawtype='Unpaid leave' if t.get('configured') else None
   if a.get('in') and a.get('out'):
    duration=minutes(a['out'])-minutes(a['in'])
    if duration<0:duration+=1440
    hours=round(max(0,duration-float(t.get('breakMinutes',0)))/60,2)
   if not effective:
    status='Not employed';note='Outside policy / employment effective dates'
   elif rawtype=='Weekly off':
    off_used+=1
    if off_used<=int(t['weeklyOffDays']):status='Weekly off';credit=1
    else:status='Unpaid weekly off';lop=1;note='Monthly weekly-off allowance exceeded'
   elif rawtype=='Paid leave':
    paid_used+=1
    if paid_used<=float(t['paidLeaveDays']):status='Paid leave';credit=1
    else:status='Unpaid leave';lop=1;note='Monthly paid-leave allowance exceeded'
   elif rawtype=='Holiday':status='Holiday';credit=1
   elif rawtype in ['Unpaid leave','Absent']:status=rawtype;lop=1
   elif rawtype=='Half day':status='Half day';credit=.5;lop=.5
   elif rawtype=='Present':status='Present';credit=1;note='Manually approved full day'
   elif a.get('status') in ['Present','Late']:
    status=a.get('status');credit=1
    if a.get('review') or not a.get('in') or not a.get('out'):
     if closed:status='Needs review';credit=0;review=True;note='Missing check-out / incomplete punch sequence'
     else:status='In progress';credit=0;note='Shift has not closed'
    elif not closed:
     status='In progress';credit=0;note='Shift has not closed; final hours classification is pending'
    elif t.get('configured'):
     actual_in=minutes(a['in']);actual_out=minutes(a['out'])
     late_minutes=max(0,actual_in-start) if not overnight else 0
     early_minutes=max(0,end-actual_out) if not overnight else 0
     if hours>=float(t['dailyHours']):
      status='Late' if late_minutes>float(t.get('lateGraceMinutes',0)) else 'Present'
      note='Meets full-day work hours'
     elif hours>=float(t['halfHours']):
      status='Half day';note='Hours meet half-day threshold but are below full-day duty hours'
      if t.get('shortHours'):credit=.5;lop=.5
     else:
      status='Absent';note='Recorded work hours are below the half-day threshold'
      if t.get('shortHours'):credit=0;lop=1
     if status in ['Half day','Absent'] and not t.get('shortHours'):
      note+='; hours-based LOP is disabled, so no hours deduction is applied'
   elif a.get('status')=='Absent':status='Absent';lop=1
   elif pending:status='Pending';note='Future or unfinished workday'
   elif t.get('configured') and t.get('autoAbsent'):status='Absent';lop=1;note='No attendance on a completed scheduled workday'
   else:status='Unrecorded';review=True;note='No attendance; automatic absence deduction is disabled'
   # Future dates can be planned, but never deducted/credited in an elapsed payroll calculation.
   if pending:
    lop=0;credit=0;review=False
    if status not in ['Not employed','In progress']:note=(note+'; ' if note else '')+'Planned / not yet closed'
   if not t.get('configured') and status in ['Unpaid leave','Unpaid weekly off']:
    review=closed;note='Configure the monthly policy before payroll'
   details.append({'date':d,'weekday':date.fromisoformat(d).strftime('%A'),'dutyStart':t.get('shift','09:00'),'dutyEnd':t.get('end','18:00'),'requiredHours':float(t['dailyHours']),'halfDayHours':float(t['halfHours']),'lateMinutes':late_minutes,'earlyExitMinutes':early_minutes,'status':status,'lop':lop,'credit':credit,'review':review,'pending':pending and effective,'hours':hours,'in':a.get('in',''),'out':a.get('out',''),'source':a.get('source',''),'reason':o.get('reason','') if o else '', 'note':note,'punches':a.get('punches',[])})
  unpaid=sum(a['lop'] for a in details);adjustments=[a for a in state.get('adjustments',[]) if a['id']==uid and a['month']==month and not a.get('voided')]
  bonus=sum(float(a['amount']) for a in adjustments if a['type']=='Bonus');deduction=sum(float(a['amount']) for a in adjustments if a['type']=='Deduction')
  eligible=sum(a['status']!='Not employed' for a in details)
  divisor=len(days) if t['divisor']=='calendar' else max(1,float(t['fixedDivisor']))
  base=float(t['salary']);gross=amount(base*eligible/len(days))
  lopamount=min(gross,amount(base/divisor*unpaid))
  counts={key:sum(1 for a in details if a['status']==key and not a['pending']) for key in ['Present','Late','Weekly off','Unpaid weekly off','Paid leave','Unpaid leave','Holiday','Absent','Half day','Short hours','Needs review','Unrecorded']}
  rows.append({**staff,'salary':base,'policy':t,'days':details,'counts':counts,'eligibleDays':eligible,'calendarDays':len(days),'divisor':divisor,'gross':gross,'unpaid':unpaid,'lop':lopamount,'bonus':amount(bonus),'deduction':amount(deduction),'net':amount(gross-lopamount+bonus-deduction),'paidDays':sum(a['credit'] for a in details),'recorded':sum(bool(a['source']) for a in details),'reviewDays':sum(a['review'] for a in details),'pendingDays':sum(a['pending'] for a in details),'configured':t['configured'],'adjustments':adjustments})
 return {'month':month,'asOf':now.isoformat(),'rows':rows,'formula':'Gross salary (prorated for employment dates) - capped LOP + bonuses - other deductions. No tax/PF/ESI calculation.'}

def _render_payslip_pdf(row,month,issued=None,company=None):
 from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer,Image,KeepTogether
 from reportlab.lib import colors
 from reportlab.lib.styles import ParagraphStyle
 from reportlab.lib.enums import TA_RIGHT
 from reportlab.lib.pagesizes import A4
 from html import escape
 from company_profile import DEFAULT_COMPANY
 import io,base64
 c={**DEFAULT_COMPANY,**(company or {})}
 output=io.BytesIO();ink=colors.HexColor('#193c32');grey=colors.HexColor('#6b7973');pale=colors.HexColor('#edf4e8')
 doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=34,bottomMargin=34)
 width=A4[0]-84
 styles={
  'name':ParagraphStyle('company',fontName='Helvetica-Bold',fontSize=17,leading=20,textColor=colors.HexColor('#c9ee9c')),
  'address':ParagraphStyle('address',fontName='Helvetica',fontSize=8,leading=11,textColor=colors.white),
  'doc':ParagraphStyle('doc',fontName='Helvetica-Bold',fontSize=13,leading=19,textColor=colors.white,alignment=TA_RIGHT),
  'note':ParagraphStyle('note',fontName='Helvetica',fontSize=8,leading=11,textColor=grey),
  'employee':ParagraphStyle('employee',fontName='Helvetica-Bold',fontSize=17,leading=21,textColor=ink),
  'section':ParagraphStyle('section',fontName='Helvetica-Bold',fontSize=10,leading=14,textColor=ink),
  'value':ParagraphStyle('value',fontName='Helvetica',fontSize=10,leading=14,textColor=ink,alignment=TA_RIGHT),
  'cell':ParagraphStyle('cell',fontName='Helvetica',fontSize=10,leading=14,textColor=grey)}
 def para(value,style='note'):return Paragraph(escape(str(value)).replace('\n','<br/>'),styles[style])
 profile=[para(c['name'],'name')]
 if c.get('legalName') and c['legalName']!=c['name']:profile.append(para(c['legalName'],'address'))
 for value in [c.get('address'), ' | '.join(x for x in [c.get('email'),c.get('phone')] if x),c.get('website'),' | '.join(x for x in [('Tax ID: '+c['taxId']) if c.get('taxId') else '',('Registration: '+c['registrationNumber']) if c.get('registrationNumber') else ''] if x)]:
  if value:profile.append(para(value,'address'))
 docblock=[para('PAYSLIP','doc'),para(month,'doc'),para('ISSUED' if issued else 'DRAFT - FOR REVIEW','address')]
 if c.get('logo'):
  raw=base64.b64decode(c['logo'].split(',',1)[1]);logo=Image(io.BytesIO(raw),width=52,height=52,kind='proportional')
  header=Table([[logo,profile,docblock]],colWidths=[76,width-219,143])
 else:header=Table([[profile,docblock]],colWidths=[width-143,143])
 header.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),ink),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),17),('BOTTOMPADDING',(0,0),(-1,-1),17)]))
 story=[header,Spacer(1,24),para(row['name'],'employee'),Spacer(1,6),para('Employee ID: '+str(row['id'])+'  |  Section: '+str(row.get('section',''))+'  |  Role: '+str(row.get('role','Staff'))),Spacer(1,22),para('ATTENDANCE SUMMARY','section'),Spacer(1,8)]
 attendance=[('Calendar days',row['calendarDays']),('Paid work / leave / off credits',row['paidDays']),('Paid weekly offs',row['counts']['Weekly off']),('Paid leave',row['counts']['Paid leave']),('Unpaid equivalent days',row['unpaid']),('Days awaiting review',row['reviewDays']),('Future / unfinished days',row['pendingDays'])]
 def data_table(values):
  t=Table([[para(label,'cell'),para(value,'value')] for label,value in values],colWidths=[width-145,145])
  t.setStyle(TableStyle([('ALIGN',(1,0),(1,-1),'RIGHT'),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#e8ede8')),('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),7)]))
  return t
 story.extend([data_table(attendance),Spacer(1,20),para('PAY BREAKDOWN (INR)','section'),Spacer(1,8)])
 pay=[('Monthly salary',row['salary']),('Gross for eligible employment dates',row['gross']),('Bonuses',row['bonus']),('Loss of pay',-row['lop']),('Other deductions',-row['deduction'])]
 story.append(data_table([(label,format(value if value else 0,',.2f')) for label,value in pay]));story.append(Spacer(1,14))
 net=Table([[Paragraph('NET PAY (INR)',ParagraphStyle('netlabel',fontName='Helvetica-Bold',fontSize=12,textColor=ink)),Paragraph(format(row['net'],',.2f'),ParagraphStyle('net',fontName='Helvetica-Bold',fontSize=19,textColor=ink,alignment=TA_RIGHT))]],colWidths=[width-190,190]);net.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),15),('BOTTOMPADDING',(0,0),(-1,-1),15)]));story.extend([net,Spacer(1,22)])
 story.append(para('Basis: monthly salary / '+str(row['divisor'])+' x unpaid equivalent days. LOP is capped at gross.'))
 story.append(para('Tax, PF and ESI are not calculated. This document does not confirm a bank payment.'))
 story.append(para('Issued reference: '+issued['reference'] if issued else 'Draft includes known deductions only; pending/review days may change payroll.'))
 if c.get('documentFooter'):story.extend([Spacer(1,8),para(c['documentFooter'])])
 story.extend([Spacer(1,8),para('Generated '+datetime.now(IST).strftime('%d %b %Y %H:%M IST')+' | '+c['name'])])
 doc.build(story);return output.getvalue()


def payslip_pdf(row,month,issued=None,company=None):
 try:
  import reportlab
 except ImportError:
  import os,subprocess,json
  from pathlib import Path
  interpreter=os.environ.get('GAMEFIT_PDF_PYTHON')
  if not interpreter:raise RuntimeError('PDF dependencies are unavailable. Install requirements.txt or configure GAMEFIT_PDF_PYTHON.')
  result=subprocess.run([interpreter,str(Path(__file__).with_name('pdf_worker.py'))],input=json.dumps({'row':row,'month':month,'issued':issued,'company':company}).encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
  if result.returncode:raise RuntimeError('PDF renderer failed: '+result.stderr.decode()[-300:])
  return result.stdout
 return _render_payslip_pdf(row,month,issued,company)
