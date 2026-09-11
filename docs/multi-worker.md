# Multi-worker setup

The Windows launchers run two isolated app instances:

| Worker | Port | Local environment | Runtime data |
|---|---:|---|---|
| Primary | 3169 | `.env.local` | `data/` |
| Worker 2 | 3170 | `.env.worker-3170.local` | `data/workers/3170/` |

Worker 3 (`3171`) is available on disk (setup/start/login scripts under
`scripts/`) but is no longer launched by `start_all_workers.ps1`. Bring it back
by re-adding the launcher line or running `start_flow_worker_3171.ps1` directly.

Each secondary worker must have a separate Trello input list and separate
Google Flow browser profiles. Account emails, project IDs, cookies, tokens,
generated images, and runtime state are local-only and ignored by Git.

## Configure a secondary worker

1. Copy the credentials from `.env.local` into a worker environment by running
   its setup script once.
2. Add the worker's `TRELLO_BOARD_ID`, `TRELLO_LIST_ID`, profile map, and project
   map to its local environment file.
3. Open each browser profile and complete Google sign-in.

Example `.env.worker-3170.local` values:

```env
TRELLO_BOARD_ID=your-board-id
TRELLO_LIST_ID=your-worker-list-id
FLOW_CHROME_PROFILE_DIRS=AccountA=data\workers\3170\flow-profiles\account-a;AccountB=data\workers\3170\flow-profiles\account-b
FLOW_CHROME_PROFILE_PROJECTS=AccountA=project-id-a;AccountB=project-id-b
```

Open a profile for login without storing account details in a script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\login_flow_profile.ps1 `
  -ProfileDir "data\workers\3170\flow-profiles\account-a" `
  -ProjectUrl "https://labs.google/fx/vi/tools/flow/project/your-project-id" `
  -Label "Worker 2 account A"
```

## Start workers

```powershell
# Start Primary + Worker 2 without opening dashboard tabs.
powershell -ExecutionPolicy Bypass -File .\scripts\start_all_workers.ps1 -NoOpenBrowser

# Start Worker 2 on its own.
powershell -ExecutionPolicy Bypass -File .\scripts\start_flow_worker_3170.ps1

# (Optional) Re-enable Worker 3 by launching it manually.
powershell -ExecutionPolicy Bypass -File .\scripts\start_flow_worker_3171.ps1
```

The launchers use separate `FLOW_DATA_DIR` and `FLOW_ENV_FILE` values, so reset,
history, downloads, and job state remain isolated per worker.
