# run-of-show

A theatrical cue-calling tool. You build a cue list for a production (by hand, or imported from a spreadsheet or an ETC Eos export); during a run, a stage manager hits **GO** to fire the cues in order, and every GO, BACK, GOTO and RESET is written to an append-only run log that can be played back later with its real timing. The frontend is an animated run-of-show board. This is a personal proof project, built to practise Django and GSAP with a domain I know from nine years of running shows. It is not client work and has not been used on a real production.

![The run-of-show board: a cue is loaded and fired, BACK steps back, then the run is played back at speed](docs/run-of-show.gif)

## Stack

- **Backend:** Python 3.12, Django 5.2, Django REST Framework, PostgreSQL 17 (via Docker Compose)
- **Frontend:** React 19, Vite, GSAP 3 (with `@gsap/react`)
- **Tests:** pytest-django (backend), Vitest (frontend)

## Running it

You need Docker, Python 3.12, and Node 20.19+ or 22.12+.

**Database**

```bash
docker compose up -d --wait
```

**Backend** (http://localhost:8000)

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py seed_demo
.venv/bin/python manage.py runserver
```

`seed_demo` creates a local demo user (`demo` / `curtain-up`, an app admin) and a sample production with ten cues. It is safe to run more than once. Anyone can also create their own account from the sign-in page. For the Django admin, create a superuser with `manage.py createsuperuser`.

Password reset emails are printed to the `runserver` console in development; the link in them opens the frontend at `FRONTEND_URL`. To send real email, set `EMAIL_BACKEND` and the `EMAIL_*` settings (see `backend/.env.example`).

**Frontend** (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

The login form is prefilled with the demo account. Set `VITE_API_URL` (see `frontend/.env.example`) if the API is not on `localhost:8000`.

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

Four models in `backend/shows/models.py`, all registered in the Django admin:

- `Production`: owner, name, company, venue, performance date, notes
- `Membership`: someone else on a production, as stage manager, operator or viewer
- `Cue`: number (a decimal, so `12.5` sorts between `12` and `13`), label, script page, notes, scene, and timing as on Eos: up time, down time, Eos's total duration, and follow or hang (`F2`, `H3`). Cues are always ordered by number.
- `Run`: one rehearsal or performance of a production (label such as "Preview 1", kind, start and end)
- `CueEvent`: one operator action in a run (GO, BACK, GOTO or RESET), with the cue it made active and a timestamp

The schema is in the committed migrations in `backend/shows/migrations/`. `0003` is a data migration that moved the original free-text run labels into `Run` rows.

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
| `GET` `PATCH` | `/api/runs/{id}/` | One run, with its event log and current state |
| `POST` | `/api/runs/{id}/go/` | Fire the next cue, or the cue given as `{"cue": id}` |
| `POST` | `/api/runs/{id}/back/` | Step back to the previous cue |
| `POST` | `/api/runs/{id}/goto/` | Fire the cue given as `{"cue": id}` |
| `POST` | `/api/runs/{id}/reset/` | Clear the active cue |
| `POST` | `/api/runs/{id}/end/` | End the run; it then refuses further actions |
| `POST` | `/api/productions/{id}/cues/import/` | Import cues from CSV (dry run unless `dry_run=false`) |
| `GET` | `/api/productions/{id}/cues/export/` | Download the cue list as CSV |
| `GET` | `/api/runs/{id}/export/` | Download a run log as CSV |

Every endpoint except sign-in, sign-up and password reset requires authentication (DRF token or session). Each user has one token: changing or resetting the password replaces it, which signs out every other device. Sign-in, sign-up and the password endpoints are rate limited (`AUTH_THROTTLE_RATE`, default 20 a minute per client). Querysets are filtered to productions the requesting user owns or is a member of, so anyone else's production, cue or run returns 404. Within a production, `backend/shows/access.py` decides what each role may do, and a member without the right role gets 403:

| Role | View and export | Run the show (GO, BACK, GOTO, RESET, runs) | Edit details and cues | Manage people | Delete |
| --- | --- | --- | --- | --- | --- |
| Owner | ✓ | ✓ | ✓ | ✓ | ✓ |
| Stage manager | ✓ | ✓ | ✓ | ✓ | |
| Operator | ✓ | ✓ | | | |
| Viewer | ✓ | | | | |

There is one app-wide level on top of that: **admin** (Django's `is_staff`), which can manage users from `/users` and `/api/admin/users/`. Admins don't see other people's productions; that still takes a membership. Suspending a user keeps their account and productions, signs them out everywhere and stops them signing in. Deleting a user is refused while they own productions, since those would go too, and an admin can't suspend, demote or delete themselves. Admins aren't held to the self-service password rules: they can set any password that isn't empty. Emails must be well-formed and unique (regardless of case) for everyone, admins included, but any number of accounts can have no email.

Each viewset lists the capability every write action needs; an action that isn't listed is refused, so a new write route can't slip through unchecked. Productions carry the requesting user's `role`, and the board only shows the controls that role can use. The server decides which cue is next: it locks the run row for each action, so two GOs at once can't fire the same cue.

**About "append-only":** this is enforced in the application layer, not the database. `CueEvent.save()` refuses to update an existing row, `CueEvent.delete()` raises, the API has no update or delete route for events, and the admin is read-only for them. The database does not block `UPDATE` or `DELETE`, and deleting a production or run cascades through its events. Each event keeps a copy of the cue's number and label, so editing or deleting a cue later does not change the log.

**CSV import** (`backend/shows/csv_io.py`) reads two formats. A simple CSV needs a header row with a `number` column, and may have `label`, `page`, `scene`, `notes`, `time`, `down_time`, `duration` and `follow` (times in seconds or `m:ss`); that is also what export writes, so an export can be edited in a spreadsheet and brought back. An **ETC Eos CSV export** (cues only, or a whole show file) is recognised by its `START_…` sections: cues come from the TARGETS section, one cue list at a time since numbers repeat across lists, part rows are skipped, and label, cue notes, scene text, time, down time, duration and follow are kept. Eos's duration is its own total for the cue, counting delays, discrete times and parts; it is what the board times the cue by, and it is cleared when a cue's time is edited here (in the app or by an import without a duration), since it can't be recomputed without those details. Every import is planned first and shown as a dry run (create, update, unchanged, delete, rejected with a reason), then planned again against the current cue list when it's applied. **Merge** adds and updates but never blanks a field (Eos leaves most labels empty); **replace** makes the file the whole cue list. The Eos reader has been checked against real exports from two shows, the larger a full show file with 10 cue lists, 401 cues in the main list, point cues, part cues, labels, scene text and cue notes; the tests use synthetic fixtures with the same shape.

The tests in `backend/shows/tests.py` cover: actions add events without changing earlier ones; unauthenticated writes get 401; one user cannot see or change another user's data; numeric cue ordering; cue editing and duplicate numbers; GO, BACK, GOTO and RESET at both ends of the list; log entries surviving a cue being renamed or deleted; ended runs; and the data migration rejecting bad cue numbers. `backend/shows/test_access.py` covers each role's capabilities, delete being owner-only, the shared productions list, adding people by username or email, changing roles and leaving. `backend/accounts/test_admin.py` covers user management: admin-only access, search, creating users, suspending and reactivating, promoting, the lock-out guards, refusing to delete an owner, and sending reset links. `backend/accounts/tests.py` covers sign-up validation, sign-in and out, profile edits, password change and reset (including single-use links and not revealing which emails have accounts), and rate limiting. `backend/shows/test_csv.py` covers both import formats, merge versus replace, rejected rows, export round trips, run logs surviving a replace import, and owner-only access.

## Frontend

Two main screens, with URLs that survive a reload (React Router): the productions list at `/`, and the run-of-show board at `/productions/{id}/runs/{run}` (`frontend/src/Board.jsx`). Signed out, there are pages to sign in, sign up (`/signup`) and reset a password (`/forgot-password`, and `/reset-password/{uid}/{token}` from the email). Admins get a **Users** link to `/users` (`frontend/src/admin/Users.jsx`). Signed in, your name in the top bar opens `/profile`, where you change your display name, email and password (`frontend/src/account/`).

Running a show (Live mode):

- Each card shows the cue's time the way Eos does (`5`, or `5/3` for up/down), any follow or hang, and Eos's total when it is longer than the time. When a cue goes, a bar along the bottom of its card fills over that total, so you can see when the cue has finished. The board shows follows and hangs but never fires them.
- **GO** (or Space) fires the next cue. **Clicking a cue loads it**: it becomes the cue GO will fire, and nothing fires until GO. ↑ and ↓ move the load; Esc clears it.
- **BACK** (B or ←) steps to the previous cue. **GOTO** fires the cue whose number is typed in its box (G jumps to the box). **RESET** clears the active cue. All three are recorded in the log alongside GOs.
- The **run picker** switches between runs, starts a new one (label and kind), or ends the current one. An ended run is read-only. **Export** downloads the run's log, with seconds from the first event.

The board has two modes, like Live and Blind on a lighting console:

- **Live** shows the cue list as cards, with scene dividers and cue notes, and is where the show is run.
- **Edit** turns the cue list into inline fields (number, label, time, follow or hang, page, scene, notes). Time takes `5`, `5/3` or `1:30`. A field saves on Enter or when it loses focus, Esc puts it back, delete asks for a second click, and new cues land in number order. **Import CSV…** opens a dialog that previews every change before anything is written; **Export CSV** downloads the list. The production's details are edited from the board header; deleting a production means typing its name. **People** in the header lists who is on the production; owners and stage managers add people by username or email, change their roles and remove them, and anyone can leave.

The Vitest tests cover the board's state helpers (`frontend/src/board/state.js`), cue time parsing and formatting (`frontend/src/board/cueTime.js`), and the step builder that turns a log into playback (`frontend/src/board/playbackSteps.js`).

The GSAP techniques used on the board:

- **Stagger:** on load, `gsap.from()` with `stagger` brings the cue cards in one after another.
- **Tweens:** GO posts to the run's `go/` endpoint, then `gsap.to()` moves each card between its pending, standby, active, and complete looks (colour, border, opacity, scale), slides the playhead along the track, and `gsap.fromTo()` adds a flash on the cue that just went. The space bar also works as GO.
- **Timeline playback:** "Play back this run" turns the run's log into one `gsap.timeline()`: every card change and playhead move is a tween placed at the real time it happened (`frontend/src/board/Playback.jsx`). Speed (1×, 2×, 5×, 20×) is `timeScale()`, the scrubber is `progress()`, and pause and play are the timeline's own. The clock and scrubber are written to the DOM from `onUpdate` rather than through React state, so playback doesn't re-render the board every frame. A run with nothing recorded plays an evenly spaced preview instead. Playback writes nothing to the log, and Stop returns the board to the run's live state.
- **Fade bars:** GO and GOTO run a linear `fromTo()` on the card's bar for the cue's duration; BACK runs it for one second, and the next action cuts it off. In playback each bar is a tween in the timeline too, ending where the next action cut it. Lag smoothing is off (`gsap.ticker.lagSmoothing(0)`), so after a stalled frame a bar jumps to where real time says it is instead of falling behind. A run with nothing recorded previews each cue for its own duration.
- `useGSAP` and `contextSafe` from `@gsap/react` scope the animations to the component so they are cleaned up on unmount.
- The card looks (`frontend/src/board/looks.js`) are frozen objects copied into every GSAP call, because GSAP writes into the vars object it is given; sharing one would let a timeline quietly change the looks for every later tween.

## Not included

There is no deployment, no real-time sync between several operators, no production hardening (the settings are for local development). These, and show-control input from an Eos console, are tracked as [GitHub issues](https://github.com/aeiti/run-of-show/issues).
