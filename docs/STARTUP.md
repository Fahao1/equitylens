# Persistent local startup on macOS

EquityLens's browser page and Python API are separate processes. During diagnosis, the old Vite frontend was still listening on port 5173 while nothing listened on 8000. The previous API belonged to a temporary command session. A subsequent launchd installation also exposed a separate macOS issue: the operating system denied background access to the Desktop project (`getcwd: Operation not permitted` and denial of `scripts/dev.sh`). No security setting was changed to work around that protection.

The persistent launcher now deploys a real runtime copy to:

`~/Library/Application Support/EquityLens`

A per-user LaunchAgent supervises that runtime's foreground `scripts/dev.sh`. It survives closing a terminal or chat, starts when that user logs in, and restarts the owned backend/frontend pair after a process exits. It runs while the user is logged in; a sleeping or powered-off Mac cannot serve the application. This follows Apple's [Launch Daemons and Agents guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).

## Open EquityLens

Double-click **EquityLens.command** in the project folder. It starts the installed service if needed, waits until both endpoints are healthy, then opens [EquityLens](http://127.0.0.1:5173). Closing the command's terminal after successful startup does not stop the app. Login startup does not automatically open a browser.

## Install or update

Dependencies remain local: the source `.venv` and `frontend/node_modules` are copied, not globally installed. The runtime uses its copied Python environment and an explicit Node search path. Review the exact plist before writing to your Library:

```bash
.venv/bin/python scripts/service.py prepare
cat data/service/com.equitylens.local.plist
```

Stop any old foreground instance from its original terminal, then install as the logged-in user, without sudo:

```bash
.venv/bin/python scripts/service.py install --open
```

The installer writes `~/Library/LaunchAgents/com.equitylens.local.plist` with owner-only permissions. It runs wholly from Application Support, rather than following a source symlink into Desktop. It records the original source path as ownership metadata, registers the job in the current GUI login session, and verifies both endpoints.

Only application code, local dependencies and the launcher are deployed. Relative Node executable links are preserved, including `.bin/vite`; dependency `dist` directories are retained. The app's top-level generated `frontend/dist` is omitted because this launcher serves Vite source. Absolute links into copied source paths are rebased to the runtime; another Desktop dependency causes a clear installation failure instead of expanded access.

The installer refuses an occupied unmanaged port and never kills its listener. It also refuses to overwrite another checkout's installed agent or unrecognized runtime files. To move to another source checkout, uninstall from the old checkout first, then explicitly install from the new one. The recognized runtime data is retained.

## Data and source of truth

- **Code:** the Desktop project remains the editable source of truth. Explicit `install` refreshes runtime code and dependencies. Ordinary `start` or double-click does not resync source changes.
- **Personal data after migration:** the runtime database is authoritative: `~/Library/Application Support/EquityLens/data/equitylens.db`. On first deployment, the configured source SQLite application database is copied with SQLite's transactionally consistent backup API, including watchlists, reports, provider snapshots, calendar imports and published screening tables. The source database remains untouched.
- **Settings:** the project's `.env`, when present, is copied once with private permissions. An absolute Desktop SQLite URL is rebased to the migrated runtime database, and the data directory is set to the runtime. External database URLs are preserved. Later installs preserve the runtime `.env` and database instead of overwriting them with older source copies.
- **Credentials:** no yfinance cookie store, authentication cache, home-directory settings or unrelated ignored folders are migrated. Optional application keys stay in the runtime's private `.env` file and never enter the plist.

Do not edit or delete the runtime data to update code. Run explicit `install` for source updates. For settings changes after migration, edit the runtime `.env`, then stop/start the service. The source foreground development launcher continues using its own source configuration/database; it is not a bidirectional data-sync tool.

## Start, stop, status and removal

From the source project root:

```bash
.venv/bin/python scripts/service.py status
.venv/bin/python scripts/service.py start --open
.venv/bin/python scripts/service.py stop
.venv/bin/python scripts/service.py uninstall
```

`stop` disables automatic launch until the next explicit `start` or `install`. `uninstall` stops the owned service and removes only its installed plist. It preserves the runtime database/settings and all source files. Explicit `install` updates a verified installation by stopping its owned processes, replacing code/dependencies and starting it again.

`./scripts/dev.sh` remains a foreground development launcher: Ctrl+C stops both children. Run it only when the persistent service is stopped. Ordinary use should start through the double-click command.

## Health and logs

- API health: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- Frontend: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- Runtime API output: `~/Library/Application Support/EquityLens/data/logs/backend.log`
- Supervisor output: `service.stdout.log` and `service.stderr.log` in the same runtime log directory.

The API log records the actual copied-environment interpreter, Python version and yfinance version. The foreground supervisor starts Vite only after API health succeeds. An owned child exit stops its companion; launchd restarts the pair with a ten-second throttle. Port probes tolerate closed TCP sockets in TIME_WAIT while still refusing active listeners.

Installation reports failure instead of declaring an unverified service ready. Confirm `status` shows `ready: true`, both health URLs respond, and an owned-child restart test recovers. Read the exact startup error in the runtime logs if those checks fail. Original source logs remain available under the source `data/logs` directory for historical diagnosis.

## Tests

```bash
cd backend
../.venv/bin/python -m pytest tests/test_dev_launcher.py tests/test_service_launcher.py
```

Tests use temporary homes, mocked launchctl/HTTP and synthetic SQLite data. They do not register a service or contact external sources. They verify quoted paths, Node search paths, readiness and lifecycle handling, private ownership, occupied-port refusal, first-time data migration, settings/data preservation during updates, legacy agent upgrade, and safe Node/Python dependency links. Actual macOS installation and restart recovery are verified separately on the device.

## On-device verification

The Application Support deployment was installed successfully on this Mac. The LaunchAgent reported `ready: true`, and both backend and frontend health checks succeeded without the earlier Desktop access denial. The migrated application database retained the published screening data: 428 discovered members, 15 deeply analyzed companies and 14 short-term ranked rows, along with stored research state. The source database was preserved. Nineteen isolated startup tests passed, including runtime migration/update preservation and dependency-link handling.

Automatic recovery was verified on-device at 2026-10-27T06:12:29 UTC (October 26, 2026 in Los Angeles). After terminating the verified owned backend, launchd restored both services in 2.5 seconds: backend PID 11537 → 12466 and frontend PID 11611 → 12477. The supervisor was owned by macOS launchd (parent PID 1), and a subsequent NVDA research request returned HTTP 200. See recorded startup evidence (`STARTUP_LIVE_VERIFICATION.json`, retained locally).
