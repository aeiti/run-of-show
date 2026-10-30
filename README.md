# run-of-show

A theatrical cue-calling tool. You build a cue list for a production; during a run, a stage manager hits **GO** to fire the cues in order, and every fire is written to an append-only run log. The frontend is an animated run-of-show board. This is a personal proof project, built to practise Django and GSAP with a domain I know from nine years of running shows. It is not client work and has not been used on a real production.

![The run-of-show board: cues stagger in, GO advances the active cue and the playhead, then a preview run sequences through the whole list](docs/run-of-show.gif)

## Stack

- **Backend:** Python 3.12, Django 5.2, Django REST Framework, PostgreSQL 17 (via Docker Compose)
- **Frontend:** React 19, Vite, GSAP 3 (with `@gsap/react`)
- **Tests:** pytest-django

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

`seed_demo` creates a local demo user (`demo` / `curtain-up`) and a sample production with ten cues. It is safe to run more than once. For the Django admin, create a superuser with `manage.py createsuperuser`.

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

## Backend

Four models in `backend/shows/models.py`, all registered in the Django admin:

- `Production`: owner, name, company, venue, performance date, notes
- `Cue`: number (a decimal, so `12.5` sorts between `12` and `13`), label, script page, notes, scene. Cues are always ordered by number.
- `Run`: one rehearsal or performance of a production (label such as "Preview 1", kind, start and end)
- `CueEvent`: one operator action in a run (GO, BACK, GOTO or RESET), with the cue it made active and a timestamp

The schema is in the committed migrations in `backend/shows/migrations/`. `0003` is a data migration that moved the original free-text run labels into `Run` rows.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/token/` | Exchange username and password for an API token |
| `GET` `POST` | `/api/productions/` | List or create your productions |
| `GET` `PUT` `PATCH` `DELETE` | `/api/productions/{id}/` | One production |
| `GET` `POST` | `/api/productions/{id}/cues/` | List or add cues |
| `GET` `PUT` `PATCH` `DELETE` | `/api/cues/{id}/` | One cue |
| `GET` `POST` | `/api/productions/{id}/runs/` | List or start runs |
| `GET` `PATCH` | `/api/runs/{id}/` | One run, with its event log and current state |
| `POST` | `/api/runs/{id}/go/` | Fire the next cue, or the cue given as `{"cue": id}` |
| `POST` | `/api/runs/{id}/back/` | Step back to the previous cue |
| `POST` | `/api/runs/{id}/goto/` | Fire the cue given as `{"cue": id}` |
| `POST` | `/api/runs/{id}/reset/` | Clear the active cue |
| `POST` | `/api/runs/{id}/end/` | End the run; it then refuses further actions |

Every endpoint requires authentication (DRF token or session). Querysets are filtered to the requesting user, so another user's production, cue or run returns 404. The server decides which cue is next: it locks the run row for each action, so two GOs at once can't fire the same cue.

**About "append-only":** this is enforced in the application layer, not the database. `CueEvent.save()` refuses to update an existing row, `CueEvent.delete()` raises, the API has no update or delete route for events, and the admin is read-only for them. The database does not block `UPDATE` or `DELETE`, and deleting a production or run cascades through its events. Each event keeps a copy of the cue's number and label, so editing or deleting a cue later does not change the log.

The tests in `backend/shows/tests.py` cover: actions add events without changing earlier ones; unauthenticated writes get 401; one user cannot see or change another user's data; numeric cue ordering; cue editing and duplicate numbers; GO, BACK, GOTO and RESET at both ends of the list; log entries surviving a cue being renamed or deleted; ended runs; and the data migration rejecting bad cue numbers.

## Frontend

Two screens, with URLs that survive a reload (React Router): the productions list at `/`, and the run-of-show board at `/productions/{id}/runs/{run}` (`frontend/src/Board.jsx`).

Running a show (Live mode):

- **GO** (or Space) fires the next cue. **Clicking a cue loads it**: it becomes the cue GO will fire, and nothing fires until GO. ↑ and ↓ move the load; Esc clears it.
- **BACK** (B or ←) steps to the previous cue. **GOTO** fires the cue whose number is typed in its box (G jumps to the box). **RESET** clears the active cue. All three are recorded in the log alongside GOs.
- The **run picker** switches between runs, starts a new one (label and kind), or ends the current one. An ended run is read-only.

The board has two modes, like Live and Blind on a lighting console:

- **Live** shows the cue list as cards, with scene dividers and cue notes, and is where the show is run.
- **Edit** turns the cue list into inline fields (number, label, page, scene, notes). A field saves on Enter or when it loses focus, Esc puts it back, delete asks for a second click, and new cues land in number order. The production's details are edited from the board header; deleting a production means typing its name.

Run `npm test` in `frontend/` for the Vitest tests of the board's state helpers (`frontend/src/board/state.js`).

The GSAP techniques used on the board:

- **Stagger:** on load, `gsap.from()` with `stagger` brings the cue cards in one after another.
- **Tweens:** GO posts to the run's `go/` endpoint, then `gsap.to()` moves each card between its pending, standby, active, and complete looks (colour, border, opacity, scale), slides the playhead along the track, and `gsap.fromTo()` adds a flash on the cue that just went. The space bar also works as GO.
- **Timeline playback:** "Play back this run" turns the run's log into one `gsap.timeline()`: every card change and playhead move is a tween placed at the real time it happened (`frontend/src/board/Playback.jsx`). Speed (1×, 2×, 5×, 20×) is `timeScale()`, the scrubber is `progress()`, and pause and play are the timeline's own. The clock and scrubber are written to the DOM from `onUpdate` rather than through React state, so playback doesn't re-render the board every frame. A run with nothing recorded plays an evenly spaced preview instead. Playback writes nothing to the log, and Stop returns the board to the run's live state.
- `useGSAP` and `contextSafe` from `@gsap/react` scope the animations to the component so they are cleaned up on unmount.

## Not included

There is no deployment, no real-time sync between several operators, and no production hardening (the settings are for local development).
