# Gamefit Payroll

Attendance and payroll management for Gamefit Lively, with a modern dashboard, eSSL biometric imports, monthly policies, leave management, payroll registers, PDF payslips and company branding.

## Two supported modes

- **Local:** run `Start-Gamefit.command` on a Mac on the device network. Records are kept in SQLite. The installed background service on the original Mac uses `~/Library/Application Support/Gamefit Workforce/`; portable installations use `data/` beside the source. Open http://127.0.0.1:8780.
- **Vercel:** deploy the `api/index.py` handler with Postgres. The cloud app requires an admin login. An always-on local bridge reads the terminal and sends attendance to the cloud over HTTPS. See [DEPLOYMENT.md](DEPLOYMENT.md).

Connecting the biometric machine to the internet does **not** make its private IP reachable from Vercel. Keep a bridge computer awake on its local network. No inbound port forwarding is required.

## Main screens

- **Staff directory:** add/edit staff; app-only deletion with last working day; restore deleted staff; preserve attendance and payslip history.
- **Attendance:** daily monitoring, dated weekdays, punch in/out, and monthly registers. Individual history includes a Monday-to-Sunday calendar and a detailed list.
- **Shifts & policies:** per-person monthly salary, duty times, full/half-day hours, break minutes, grace time, paid leave, paid weekly-off allowance/dates, and LOP divisor.
- **Leave management:** paid/unpaid leave and approvals. Approved leave is compared with the monthly allowance.
- **Payroll:** explainable day credits, leave/off totals, LOP, bonuses, deductions and review snapshots. CSV exports include company identity and attendance timings.
- **Payslips:** download draft PDFs; issue an immutable snapshot when salary/policy and attendance are ready. Issuance does not send a bank payment.
- **Company admin:** company/display/legal name, address, logo/profile image, email, phone, website, tax/registration IDs, payslip prefix and document footer. New documents use these details; issued payslips preserve their original branding.
- **Device users:** view actual machine enrollments and explicitly delete a selected enrollment. The typed-ID acknowledgement is required. This can remove biometric enrollment and may require re-enrollment. App deletion is separate.

## Attendance and payroll rules

The connector preserves numeric device IDs and imports names when present. Raw punch times are retained. Work hours use the first-to-last span minus the configured break; split and overnight shifts need review.

After the duty period closes, configured thresholds classify Present, Late, Half day, or Absent. Missing IN/OUT remains a review item. Future/unfinished days remain pending. Hours-based LOP and automatic absence deductions are separate options; enabling a classification does not silently enable a salary penalty.

Paid leave and weekly offs consume their monthly allowances chronologically. Off dates must be scheduled. Overlaps do not count twice. Excess approved leave/off days become unpaid. Allowances reset monthly without carry-forward. Salary is prorated for employment/policy effective dates and the last working day.

Draft net pay = eligible gross − capped LOP + active bonuses − active deductions. Tax, PF, ESI, automatic overtime and statutory payroll compliance are not implemented. Review results before payment.

## Device deletion

This feature uses the device's specific-user deletion command, followed by a fresh enrolled-user read. It never clears all users or attendance logs. The last privileged device administrator is protected. A changed internal UID/name stops the operation. A connection failure after sending a deletion is marked **Uncertain**, not automatically retried. No biometric template backups are created.

Cloud deletion is queued only by a signed-in administrator after the specific-ID confirmation. The bridge can claim existing jobs but cannot create payroll edits or deletion requests. Queued requests expire after 15 minutes; interrupted executions require manual inspection.

No live enrollment has been deleted as part of installing or testing the feature. Destructive behavior was tested with simulated SDK objects, not by removing a real employee.

## Development and checks

Python 3.12 is configured for Vercel. Install `requirements.txt`, then run:

```sh
python -m unittest discover -s tests -v
```

Local operation uses only the SDK and PDF dependencies; Postgres is used only in cloud mode. The original Mac can use its existing bundled PDF renderer through `GAMEFIT_PDF_PYTHON`; a fresh deployment installs ReportLab normally.

Never commit `data/`, `.env*` secrets, SQLite files, employee backups or bridge cursor files. The supplied `.gitignore` and `.vercelignore` exclude them. Source code contains no real staff records or credentials.
