# Deploy to Vercel with Postgres

The source is prepared for Vercel's Python function runtime and a Postgres provider such as Neon or Supabase. A real deployment still requires your database, Vercel environment and connector configuration. Local live operation is independent and continues until you choose to migrate.

## 1. Create the database

Create a Postgres project and copy its **pooled** connection string with TLS enabled. Neon Free can be used to start; continuous usage and storage/transfer are subject to that plan's limits. A free database is not an unlimited production service.

Use a private terminal/environment for real credentials. Never put them in Git or paste them into a public issue.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DATABASE_URL='your private TLS Postgres connection string'
.venv/bin/python scripts/init_cloud_db.py
```

Initialization creates workspace, attendance, login-rate-limit, connector-heartbeat and device-command tables. Attendance dates are stored individually, not as a SQLite file in a Vercel function.

## 2. Create the admin login and connector secret

Run the password helper in your own terminal:

```sh
.venv/bin/python scripts/make_admin_hash.py
```

It prompts without echoing the password and prints its PBKDF2 hash. Put that hash in Vercel as `GAMEFIT_ADMIN_PASSWORD_HASH`. Do not put the plaintext password in the repository.

Generate **two different** random secrets locally (one for sessions, one for the bridge):

```sh
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Use the outputs for `GAMEFIT_SESSION_SECRET` and `GAMEFIT_DEVICE_SYNC_TOKEN`. The bridge token does not grant admin access to salaries or company settings.

## 3. Configure Vercel

Import your GitHub repository. Use the repository root, **Other** as the framework preset if asked, no frontend build command, and no static output directory. The checked-in `vercel.json` routes the app to the Python handler. Python 3.12 is selected in `.python-version`.

Set these environment variables for the Production deployment:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Pooled TLS Postgres URL |
| `APP_ORIGIN` | Exact HTTPS production origin, with no path, e.g. `https://your-project.vercel.app` |
| `GAMEFIT_ADMIN_PASSWORD_HASH` | Output from the password helper |
| `GAMEFIT_SESSION_SECRET` | Random session secret, at least 32 characters |
| `GAMEFIT_DEVICE_SYNC_TOKEN` | Different random bridge secret, at least 32 characters |

Redeploy after setting them. If a custom domain is added, update `APP_ORIGIN` to the exact origin you will use, then redeploy. Preview deployments need their own matching origin/environment. Do not expose the database URL to browser JavaScript.

Open the deployment and sign in. Access fails closed while admin configuration is missing. Sessions use Secure/HttpOnly cookies, same-origin write checks, a 12-hour lifetime and persistent login rate limits. This version has one admin account; multi-user roles/SSO are not implemented.

Vercel's Hobby plan is restricted to personal/non-commercial use. Choose an appropriate business plan for Gamefit. Git pushes update application code; company/staff changes persist in the database without a Git push.

## 4. Migrate the existing local workspace

Export **Reports → Workspace backup** from the local app and keep that file private. After database initialization, import it **before** starting the bridge:

```sh
.venv/bin/python scripts/import_backup.py /private/path/workforce-backup.json
```

The script accepts JSON or gzip JSON and refuses to overwrite a non-empty cloud workspace. It migrates staff, attendance, policies, leave, adjustments, document snapshots and company settings. It does not upload anything to GitHub. Keep the original local app and its backup until you have checked cloud records.

After migration, make operational edits in one workspace; this is not a bidirectional salary/settings synchronization system. The bridge sends device data only. Running both local and cloud interfaces does not synchronize their manual changes.

## 5. Run the connector near the biometric device

The bridge must run on an always-on Mac/PC or small computer on the terminal's LAN. Device internet access alone is not sufficient.

Set these environment variables on that computer:

```sh
export GAMEFIT_CLOUD_URL='https://your-project.vercel.app'
export GAMEFIT_DEVICE_SYNC_TOKEN='the private bridge secret'
export GAMEFIT_DEVICE_IP='192.168.1.40'
export GAMEFIT_DEVICE_PORT='4370'
export GAMEFIT_COMM_KEY='0'
export GAMEFIT_SYNC_INTERVAL='60'
```

For the original Mac, the existing local service already reads the machine. Use its loopback API to avoid two SDK clients polling at once:

```sh
export GAMEFIT_LOCAL_API='http://127.0.0.1:8780'
.venv/bin/python bridge.py --once
.venv/bin/python bridge.py
```

Wait for a successful local device sync after installing the update, so enrolled IDs and internal UIDs are present. The cloud bridge forwards raw device punches and device names, not local salary/settings changes. Local manual punch corrections should be migrated with the workspace backup and maintained in the cloud after migration.

On a separate connector computer without the local app, omit `GAMEFIT_LOCAL_API`; the bridge reads the device directly. Use your OS's normal service manager to keep `bridge.py` running across logins/restarts. This source package does not install a new credential-bearing bridge service automatically.

`bridge.py --once --full` replays historical punches when needed. IDs/timestamps are deduplicated. The cursor is committed only after successful uploads. Incremental sync sends new punches and recent late arrivals in batches of at most 1,000; heartbeats keep device availability visible. Old backfills outside the recent window can be replayed with `--full`.

If the bridge stops, the cloud retains saved records but cannot receive new live punches or execute confirmed device commands. The cloud shows disconnected status after three minutes without a heartbeat. Keep the computer awake and on the device network. No router port-forwarding is required.

## 6. Verify before payroll

- Sign-in is required on a fresh browser.
- The cloud Device & sync page shows a recent heartbeat and the expected device-user/punch counts.
- Check a known employee/date against the terminal's punches and configured policy.
- Enter the company profile and generate a draft payslip; verify name, address and logo.
- Configure employee salary, duty timings, paid leave and off dates.
- Download a CSV and a draft payslip before issuing the month's documents.
- Test device deletion only when you intentionally want to remove a specific enrollment. It may require re-enrollment and is not reversible through Restore staff.

The supplied tests cover application logic, authentication boundaries, ingestion scope, optimistic updates and simulated device deletion. A real Vercel/Postgres deployment cannot be certified until actual service credentials and deployment access are supplied.

References: https://vercel.com/docs/functions/runtimes/python/api-directory ; https://vercel.com/docs/plans/hobby ; https://neon.com/pricing
