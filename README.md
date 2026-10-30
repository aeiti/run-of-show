# run-of-show

A theatrical cue-calling tool. You build a cue list for a production (by hand, or imported from a spreadsheet or an ETC Eos export); during a run, a stage manager hits **GO** to fire the cues in order, and every GO, BACK, GOTO, RESET and HOLD is written to an append-only run log that can be played back later with its real timing. The frontend is an animated run-of-show board. This is a personal proof project, built to practise Django and GSAP with a domain I know from nine years of running shows. It is not client work and has not been used on a real production.

![The run-of-show board: a cue is loaded and fired, BACK steps back, then the run is played back at speed](docs/run-of-show.gif)

## Stack

- **Backend:** Python 3.12, Django 5.2, Django REST Framework, PostgreSQL 17 (via Docker Compose)
- **Frontend:** React 19, Vite, GSAP 3 (with `@gsap/react`)
- **Tests:** pytest-django (backend), Vitest (frontend)

## Running it

**Everything in Docker**

The ports are lighting colour temperatures: the board is on 3200 (tungsten, the stage) and the API on 5600 (daylight).

```bash
docker compose up -d --build
```

This runs the database, the API at http://localhost:5600 and the board at http://localhost:3200. The source folders are mounted into the containers, so edits reload as they do on the host. The API applies migrations each time it starts, so after pulling, `docker compose up -d --build` (or `docker compose restart backend`) is enough; rebuild when `requirements.txt` or `package.json` change. Run management commands inside the container, e.g. `docker compose exec backend python manage.py seed_demo`. Uploaded files are kept in the `media` volume.

**From other machines** (a tablet at the tech table, say): set `LAN_HOSTS` to the names or addresses this machine has on the network, in a `.env` file next to `docker-compose.yml` or in the shell, and restart:

```bash
LAN_HOSTS=adams-macbook-pro.local,192.168.1.241 docker compose up -d
```

Then open `http://<one of those>:3200` on the other machine. The board calls the API on port 5600 of whichever host it was loaded from, and `LAN_HOSTS` is what lets Django, the live-update sockets and Vite accept those names. Without it only this machine can use the app. macOS may ask whether to accept incoming connections the first time. This is for a trusted network: it is still the development setup, with `DEBUG` on. The database is only published on `127.0.0.1`.

**Or on the host**

You need Docker, Python 3.12, and Node 20.19+ or 22.12+.

**Database**

```bash
docker compose up -d --wait db
```

**Backend** (http://localhost:5600)

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver 5600
```

`seed_demo` creates a local demo user (`demo` / `curtain-up`, an app admin) and a sample production with ten cues. It is safe to run more than once. Anyone can also create their own account from the sign-in page. For the Django admin, create a superuser with `manage.py createsuperuser`.

`runserver` serves ASGI through Daphne, so the same server handles the API and the live-update WebSockets. After pulling this change into an existing checkout, install the new requirements (`channels`, `daphne`, `pytest-asyncio`) or `runserver` won't start.

Uploaded scripts, showfiles and logos are stored in `backend/media/` (gitignored), or in S3 or an S3-compatible service when `AWS_STORAGE_BUCKET_NAME` is set (see "Files" below and `backend/.env.example`).

Password reset emails are printed to the `runserver` console in development; the link in them opens the frontend at `FRONTEND_URL`. To send real email, set `EMAIL_BACKEND` and the `EMAIL_*` settings (see `backend/.env.example`).

**Frontend** (http://localhost:3200)

```bash
cd frontend
npm install
npm run dev
```

The login form is prefilled with the demo account. The board calls the API on port 5600 of the host it was loaded from; set `VITE_API_URL` (see `frontend/.env.example`) if the API is somewhere else. To use a host-run board from other machines, set `LAN_HOSTS` in `backend/.env` and in the shell that runs `npm run dev`, and run Vite with `--host`.

**Tests**

```bash
cd backend
.venv/bin/pytest
```

```bash
cd frontend
npm test
```

CI (`.github/workflows/ci.yml`) runs on every pull request and push to `main`. The backend job checks that migrations match the models, then runs pytest against a Postgres 17 service. The frontend job runs lint, the tests and the build.

## Backend

Seven models in `backend/shows/models.py`, all registered in the Django admin:

- `Production`: owner, name, company, venue, opening and closing dates (either may be blank; closing can't be before opening), notes, and an optional logo
- `Membership`: someone else on a production, as stage manager, operator or viewer
- `Cue`: number (a decimal, so `12.5` sorts between `12` and `13`), label, script page, notes, scene, and timing as on Eos: up time, down time, Eos's total duration, and follow or hang (`F2`, `H3`). Cues are always ordered by number.
- `Run`: one rehearsal or performance of a production: label such as "Preview 1", kind, scheduled start, actual start and end, and notes. The first GO or GOTO records the actual start (a hold, a reset or BACK doesn't) and **End run** the end; operators can correct all three times afterwards, and a run can't end before it starts. Runs are listed newest record first, not by scheduled start, so performances entered ahead of time don't push tonight's run down the picker
- `CueNote`: a note about a cue in one run ("Q12 late, tech 2"), apart from the cue's standing notes. It keeps a copy of the cue's number and label, and unlike the log it can be edited and deleted
- `ProductionFile`: one version of a script (a PDF), showfile (such as Eos's `.esf`) or other file on a production: kind, the name it was uploaded with, version, size, who uploaded it and when
- `CueEvent`: one operator action in a run (GO, BACK, GOTO, RESET, HOLD or RESUME), with the cue it made active (or, for a hold or resume, the cue that was active) and a timestamp

The schema is in the committed migrations in `backend/shows/migrations/`. `0003` is a data migration that moved the original free-text run labels into `Run` rows, and `0012` one that moved each production's single performance date to its opening date and gave existing runs a start from their first GO or GOTO.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/token/` | Exchange username and password for an API token |
| `POST` | `/api/auth/signup/` | Create an account (username, email, password, optional display name); returns a token |
| `POST` | `/api/auth/logout/` | Delete your token |
| `GET` `PATCH` | `/api/auth/me/` | Your account: email, display name and preferences (a JSON object, merged on update) |
| `POST` | `/api/auth/password/` | Change your password (needs the current one); returns a new token |
| `POST` | `/api/auth/password-reset/` | Email a reset link; always 204, so it doesn't reveal who has an account |
| `POST` | `/api/auth/password-reset/confirm/` | Set a new password with the link's `uid` and `token` |
| `GET` `POST` | `/api/productions/` | List or create your productions |
| `GET` `PUT` `PATCH` `DELETE` | `/api/productions/{id}/` | One production |
| `GET` `POST` | `/api/productions/{id}/cues/` | List or add cues |
| `GET` `PUT` `PATCH` `DELETE` | `/api/cues/{id}/` | One cue |
| `GET` `POST` | `/api/admin/users/` | Admins: list users (`?q=` searches) or create one |
| `GET` `PATCH` `DELETE` | `/api/admin/users/{id}/` | Admins: edit, promote, suspend (`is_active: false`) or delete a user |
| `POST` | `/api/admin/users/{id}/send-reset/` | Admins: email the user a password reset link |
| `GET` `POST` | `/api/productions/{id}/members/` | The owner and members, or add a member by `user` (username or email) and `role` |
| `PATCH` `DELETE` | `/api/memberships/{id}/` | Change a member's role, or remove them (anyone can remove themselves) |
| `GET` `POST` | `/api/productions/{id}/runs/` | List or start runs |
| `GET` `PATCH` | `/api/runs/{id}/` | One run, with its event log and current state; PATCH changes the label, kind, notes or scheduled start, or corrects `started_at` and an ended run's `ended_at` |
| `POST` | `/api/runs/{id}/go/` | Fire the next cue, or the cue given as `{"cue": id}` |
| `POST` | `/api/runs/{id}/back/` | Step back to the previous cue |
| `POST` | `/api/runs/{id}/goto/` | Fire the cue given as `{"cue": id}` |
| `POST` | `/api/runs/{id}/reset/` | Clear the active cue |
| `POST` | `/api/runs/{id}/end/` | End the run; it then refuses further actions |
| `POST` | `/api/productions/{id}/cues/import/` | Import cues from CSV (dry run unless `dry_run=false`) |
| `GET` | `/api/productions/{id}/cues/export/` | Download the cue list as CSV |
| `GET` | `/api/runs/{id}/export/` | Download a run log as CSV |
| `GET` `POST` | `/api/productions/{id}/files/` | List every version of every file, or upload one (`file`, and `kind`: `script`, `showfile` or `other`) |
| `GET` `DELETE` | `/api/files/{id}/` | One version of a file: its details, or delete it |
| `GET` | `/api/files/{id}/download/` | Download one version |
| `GET` `PUT` `DELETE` | `/api/productions/{id}/logo/` | The production's logo: fetch it, upload or replace it (`file`), or remove it |
| `GET` | `/api/runs/{id}/report/` | The show report as JSON: times, holds, scene lengths, cue notes and the run's notes |
| `POST` | `/api/runs/{id}/report/email/` | Email the report (text and HTML) to `to`, a list of up to 10 addresses; operators and up |

Every endpoint except sign-in, sign-up and password reset requires authentication (DRF token or session). Each user has one token: changing or resetting the password replaces it, which signs out every other device. Sign-in, sign-up and the password endpoints are rate limited (`AUTH_THROTTLE_RATE`, default 20 a minute per client), and so is emailing a show report (`REPORT_EMAIL_THROTTLE_RATE`, default 10 an hour per user). Querysets are filtered to productions the requesting user owns or is a member of, so anyone else's production, cue or run returns 404. Within a production, `backend/shows/access.py` decides what each role may do, and a member without the right role gets 403:

| Role | View, export and download files | Run the show (GO, BACK, GOTO, RESET, HOLD, runs) | Edit details, cues and files | Manage people | Delete |
| --- | --- | --- | --- | --- | --- |
| Owner | ✓ | ✓ | ✓ | ✓ | ✓ |
| Stage manager | ✓ | ✓ | ✓ | ✓ | |
| Operator | ✓ | ✓ | | | |
| Viewer | ✓ | | | | |

There is one app-wide level on top of that: **admin** (Django's `is_staff`), which can manage users from `/users` and `/api/admin/users/`. Admins don't see other people's productions; that still takes a membership. Suspending a user keeps their account and productions, signs them out everywhere and stops them signing in. Deleting a user is refused while they own productions, since those would go too, and an admin can't suspend, demote or delete themselves. Admins aren't held to the self-service password rules: they can set any password that isn't empty. Emails must be well-formed and unique (regardless of case) for everyone, admins included, but any number of accounts can have no email.

Each viewset lists the capability every write action needs; an action that isn't listed is refused, so a new write route can't slip through unchecked. Productions carry the requesting user's `role`, and the board only shows the controls that role can use. The server decides which cue is next: it locks the run row for each action, so two GOs at once can't fire the same cue.

**Live updates** (`backend/shows/live.py`, `consumers.py`): every open board keeps a WebSocket to `/ws/productions/{id}/`, so a GO, a hold, a cue edit or a note on one screen shows on every other screen at once. The socket sends the token as its first message, never in the URL, and is refused unless that user can see the production; only the frontend's own origins may open one. After each successful write the API tells the production's boards what changed: an operator action carries the event and the new state, so boards play it immediately; for anything else (cues, runs, notes, details, membership) they refetch. A member who is removed is disconnected, and a sign-out, password change or reset, suspension or deletion closes that user's sockets. Boards reconnect with backoff, refetch everything once they're back, and show "Synced" or "Reconnecting…" in the header. The channel layer is in memory, which only reaches sockets in the same process; running several processes needs a shared layer such as Redis (`CHANNEL_LAYERS`).

**About "append-only":** this is enforced in the application layer, not the database. `CueEvent.save()` refuses to update an existing row, `CueEvent.delete()` raises, the API has no update or delete route for events, and the admin is read-only for them. The database does not block `UPDATE` or `DELETE`, and deleting a production or run cascades through its events. Each event keeps a copy of the cue's number and label, so editing or deleting a cue later does not change the log.

**Files** are stored through Django's default storage: the filesystem under `MEDIA_ROOT` (default `backend/media/`) in development, or S3 when `AWS_STORAGE_BUCKET_NAME` is set (with `AWS_S3_ENDPOINT_URL` for an S3-compatible service such as MinIO or R2, and optionally `AWS_S3_REGION_NAME`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`), through `django-storages`. Nothing is published at a media URL, and S3 objects are private: a production's files are private like the rest of it, so they are only served by `/api/files/{id}/download/`, which checks the user's role, always as an attachment so an uploaded HTML or SVG file can't run as a page on the API's origin. Uploads are limited to `PRODUCTION_FILE_MAX_MB` (default 50 MB), and a script must be a PDF. Uploading a file with the same kind and name as an earlier one adds a version and keeps the others; each version can be downloaded or deleted on its own. Deleting a file, or the production, deletes the stored files too, once the database change has committed. Files are not part of the production's JSON backup, which would grow by the size of every script and showfile.

A production's **logo** is stored the same way and is just as private: the production's JSON has `logo`, null or a token that changes whenever the image does, and the image itself comes from `/api/productions/{id}/logo/`. It must be a PNG, JPEG, GIF or WebP, checked from the image's first bytes rather than its name, and at most `PRODUCTION_LOGO_MAX_MB` (default 2 MB). SVG is refused, since it can carry script. Replacing or removing a logo deletes the old image. Unlike scripts and showfiles, the logo is in the JSON backup, as base64, so an exported production imports with its logo and a duplicate gets its own copy.

**Show report** (`backend/shows/report.py`) is worked out in one place from the run's own records, and the API, the printable page and the email all use it. It has the production and run details; the scheduled and actual start, the end and the running time; each hold with its reason, cue and length, the number of holds and the total held (a hold never resumed lasts until the run ended); a length for each scene; the cue notes; and the run's notes, for incidents. Scenes stand in for act lengths: a cue's scene is the scene text on it or the nearest cue before it, and a scene runs from the first GO, GOTO or BACK into it until a cue in another scene is made active, or the run ends, with the time held within it. Going back into a scene counts it again, so a stopped and restarted rehearsal shows each pass. A run still going is measured up to when the report was made, and says so. Emails go out one per address, so recipients don't see each other, with a reply-to of the sender's email if they have one; they use the configured `EMAIL_BACKEND`, so in development they print to the `runserver` console. Times in the email are in the server's `TIME_ZONE` (UTC by default); the page shows the browser's.

**CSV import** (`backend/shows/csv_io.py`) reads two formats. A simple CSV needs a header row with a `number` column, and may have `label`, `page`, `scene`, `notes`, `time`, `down_time`, `duration` and `follow` (times in seconds or `m:ss`); that is also what export writes, so an export can be edited in a spreadsheet and brought back. An **ETC Eos CSV export** (cues only, or a whole show file) is recognised by its `START_…` sections: cues come from the TARGETS section, one cue list at a time since numbers repeat across lists, part rows are skipped, and label, cue notes, scene text, time, down time, duration and follow are kept. Eos's duration is its own total for the cue, counting delays, discrete times and parts; it is what the board times the cue by, and it is cleared when a cue's time is edited here (in the app or by an import without a duration), since it can't be recomputed without those details. Every import is planned first and shown as a dry run (create, update, unchanged, delete, rejected with a reason), then planned again against the current cue list when it's applied. **Merge** adds and updates but never blanks a field (Eos leaves most labels empty); **replace** makes the file the whole cue list. The Eos reader has been checked against real exports from two shows, the larger a full show file with 10 cue lists, 401 cues in the main list, point cues, part cues, labels, scene text and cue notes; the tests use synthetic fixtures with the same shape.

The tests in `backend/shows/tests.py` cover: actions add events without changing earlier ones; unauthenticated writes get 401; one user cannot see or change another user's data; numeric cue ordering; cue editing and duplicate numbers; GO, BACK, GOTO and RESET at both ends of the list; log entries surviving a cue being renamed or deleted; ended runs; and the data migration rejecting bad cue numbers. `backend/shows/test_cue_notes.py` covers cue notes: the cue snapshot and author, editing only the text, deleting, notes outliving their cue, notes after a run ends, validation, roles, strangers, and the backup round trip. `backend/shows/test_performance_times.py` covers opening and closing dates and their order, migration `0012`, the first GO or GOTO starting a run (and a hold, reset or a start set by hand not), scheduled starts, correcting the times and their order, ending only through End run, roles, and backups: version 1 files importing with their date as the opening, and the new fields in a version 2 export. `backend/shows/test_report.py` covers the show report: running time and lateness, hold count and totals including a hold never resumed, held time inside the run versus before it, scene lengths (with cues deleted since, BACK into a scene, a reset, and cues before the first scene), a run still going, a run never started, cue notes and run notes, the JSON endpoint, roles (a viewer reads but can't email; a stranger gets 404), the email's text and escaped HTML, one email per address, recipient validation and the limit of 10, and rate limiting. `backend/shows/test_holds.py` covers holds: the reason, cue actions refused while held, resuming where the run was, no stacked holds, ending a held run, roles and the CSV log. `backend/shows/test_access.py` covers each role's capabilities, delete being owner-only, the shared productions list, adding people by username or email, changing roles and leaving. `backend/accounts/test_admin.py` covers user management: admin-only access, search, creating users, suspending and reactivating, promoting, the lock-out guards, refusing to delete an owner, and sending reset links. `backend/accounts/tests.py` covers sign-up validation, sign-in and out, profile edits, password change and reset (including single-use links and not revealing which emails have accounts), and rate limiting. `backend/shows/test_csv.py` covers both import formats, merge versus replace, rejected rows, export round trips, run logs surviving a replace import, and owner-only access. `backend/shows/test_files.py` covers files: uploading, listing and downloading, versions, the size limit, scripts having to be PDFs, names with paths, roles (viewers and operators download but can't upload or delete), strangers, and deleting stored files with a version or the whole production; and logos: uploading, replacing and removing them (and the old image with them), refusing anything but PNG, JPEG, GIF and WebP and anything over the limit while keeping the logo there was, roles, and the logo in backups and copies. `backend/shows/test_live.py` opens real sockets and covers operator actions arriving with their state, each kind of change being announced (and reads, refused writes and dry runs not), the token handshake, strangers and foreign origins being refused, removed members being cut off, sign-out and suspension closing sockets, and deleted productions.

## Frontend

Two main screens, with URLs that survive a reload (React Router): the productions list at `/`, and the run-of-show board at `/productions/{id}/runs/{run}` (`frontend/src/Board.jsx`), with each run's printable show report at `/productions/{id}/runs/{run}/report` (`frontend/src/report/Report.jsx`). Signed out, there are pages to sign in, sign up (`/signup`) and reset a password (`/forgot-password`, and `/reset-password/{uid}/{token}` from the email). Admins get a **Users** link to `/users` (`frontend/src/admin/Users.jsx`). Signed in, your name in the top bar opens `/profile`, where you change your display name, email and password (`frontend/src/account/`).

Running a show (Live mode):

- Each card shows the cue's time the way Eos does (`5`, or `5/3` for up/down), any follow or hang, and Eos's total when it is longer than the time. When a cue goes, a bar along the bottom of its card fills over that total, so you can see when the cue has finished. The board shows follows and hangs but never fires them.
- **GO** (or Space) fires the next cue. **Clicking a cue loads it**: it becomes the cue GO will fire, and nothing fires until GO. ↑ and ↓ move the load; Esc clears it.
- **BACK** (B or ←) steps to the previous cue. **GOTO** fires the cue whose number is typed in its box (G jumps to the box). **RESET** clears the active cue. All three are recorded in the log alongside GOs.
- **Notes** (N) adds a note about a cue in this run. It's on the loaded cue, or the active one, unless you type another number. Notes show in the log and on the cue's card, and can be edited or deleted. They can be written after a run has ended.
- **HOLD…** pauses the run and asks why ("audience medical"). While it's held, GO, BACK, GOTO and RESET are off, and the panel shows the reason, how long it's been held and **RESUME**. The log shows each hold's reason and how long it lasted, and playback shows the hold for as long as it lasted.
- **Script** shows the production's script beside the cue list, in the browser's own PDF viewer, and turns to the active cue's script page on each GO. It is the script uploaded most recently. **Files** in the header lists the scripts, showfiles and other files with their versions; anyone on the production can download them, and owners and stage managers upload and delete.
- **Report** (above the log) opens the run's show report at `/productions/{id}/runs/{run}/report`: times, holds, scene lengths, cue notes, and notes and incidents, which operators write there. **Print / Save as PDF** uses the browser's print dialog with a print stylesheet; operators can also email it to a few addresses.
- The **run picker** switches between runs, starts a new one (label, kind and an optional scheduled start), or ends the current one. Under it are the run's scheduled start, when it actually started (and how late), when it ended and its running length, which counts up while the run is going; **Edit times** corrects them. An ended run is read-only. **Export** downloads the run's log, with seconds from the first event.

The board has two modes, like Live and Blind on a lighting console:

- **Live** shows the cue list as cards, with scene dividers and cue notes, and is where the show is run.
- **Edit** turns the cue list into inline fields (number, label, time, follow or hang, page, scene, notes). Time takes `5`, `5/3` or `1:30`. A field saves on Enter or when it loses focus, Esc puts it back, delete asks for a second click, and new cues land in number order. **Import CSV…** opens a dialog that previews every change before anything is written; **Export CSV** downloads the list. The production's details are edited from the board header, including a logo, which is shown there and on the productions list; deleting a production means typing its name. **People** in the header lists who is on the production; owners and stage managers add people by username or email, change their roles and remove them, and anyone can leave.

The Vitest tests cover the date and run-time helpers (`frontend/src/dates.js`), the report page's helpers (`frontend/src/report/reportText.js`), the board's state helpers (`frontend/src/board/state.js`), cue time parsing and formatting (`frontend/src/board/cueTime.js`), the step builder that turns a log into playback (`frontend/src/board/playbackSteps.js`), the live-update client's handshake, backoff, resync and sign-out handling (`frontend/src/live.js`), and grouping file versions (`frontend/src/board/files.js`).

The GSAP techniques used on the board:

- **Stagger:** on load, `gsap.from()` with `stagger` brings the cue cards in one after another.
- **Tweens:** GO posts to the run's `go/` endpoint, then `gsap.to()` moves each card between its pending, standby, active, and complete looks (colour, border, opacity, scale), slides the playhead along the track, and `gsap.fromTo()` adds a flash on the cue that just went. The space bar also works as GO.
- **Timeline playback:** "Play back this run" turns the run's log into one `gsap.timeline()`: every card change and playhead move is a tween placed at the real time it happened (`frontend/src/board/Playback.jsx`). Speed (1×, 2×, 5×, 20×) is `timeScale()`, the scrubber is `progress()`, and pause and play are the timeline's own. The clock and scrubber are written to the DOM from `onUpdate` rather than through React state, so playback doesn't re-render the board every frame. A run with nothing recorded plays an evenly spaced preview instead. Playback writes nothing to the log, and Stop returns the board to the run's live state.
- **Fade bars:** GO and GOTO run a linear `fromTo()` on the card's bar for the cue's duration; BACK runs it for one second, and the next action cuts it off. In playback each bar is a tween in the timeline too, ending where the next action cut it. Lag smoothing is off (`gsap.ticker.lagSmoothing(0)`), so after a stalled frame a bar jumps to where real time says it is instead of falling behind. A run with nothing recorded previews each cue for its own duration.
- `useGSAP` and `contextSafe` from `@gsap/react` scope the animations to the component so they are cleaned up on unmount.
- The card looks (`frontend/src/board/looks.js`) are frozen objects copied into every GSAP call, because GSAP writes into the vars object it is given; sharing one would let a timeline quietly change the looks for every later tween.

## Not included

There is no deployment, no production hardening (the settings are for local development). These, and show-control input from an Eos console, are tracked as [GitHub issues](https://github.com/aeiti/run-of-show/issues).
