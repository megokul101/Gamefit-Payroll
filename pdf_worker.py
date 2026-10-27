import sys,json
from payroll_engine import _render_payslip_pdf
if __name__=='__main__':
 x=json.load(sys.stdin);sys.stdout.buffer.write(_render_payslip_pdf(x['row'],x['month'],x.get('issued'),x.get('company')))
