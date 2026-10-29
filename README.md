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

Three models in `backend/shows/models.py`, all registered in the Django admin:

- `Production`: owner, name, venue, performance date
- `Cue`: number (a string, so `12.5` works), label, script page, order within the production
- `CueEvent`: one firing of a cue, with run label (for example "Preview 1"), timestamp, and note

The schema is in the committed migration `backend/shows/migrations/0001_initial.py`.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/auth/token/` | Exchange username and password for an API token |
| `GET` `POST` | `/api/productions/` | List or create your productions |
| `GET` `PUT` `PATCH` `DELETE` | `/api/productions/{id}/` | One production |
| `GET` `POST` | `/api/productions/{id}/cues/` | List or append cues |
| `POST` | `/api/cues/{id}/fire/` | Fire a cue: inserts a `CueEvent` and returns it |
| `GET` | `/api/productions/{id}/events/?run=…` | The run log, optionally for one run |

Every endpoint requires authentication (DRF token or session). Querysets are filtered to the requesting user, so another user's production or cue returns 404.

**About "append-only":** this is enforced in the application layer, not the database. `CueEvent.save()` refuses to update an existing row, `CueEvent.delete()` raises, the API has no update or delete route for events, and the admin is read-only for them. The database does not block `UPDATE` or `DELETE`, and deleting a production or cue cascades through its events.

The three tests in `backend/shows/tests.py` cover: firing a cue adds a new event without changing earlier ones; unauthenticated writes get 401; and one user cannot see or fire into another user's production.

## Frontend

Two screens: a productions list with a create form, and the run-of-show board (`frontend/src/Board.jsx`). The GSAP techniques used on the board:

- **Stagger:** on load, `gsap.from()` with `stagger` brings the cue cards in one after another.
- **Tweens:** GO posts to `/fire/`, then `gsap.to()` moves each card between its pending, standby, active, and complete looks (colour, border, opacity, scale), slides the playhead along the track, and `gsap.fromTo()` adds a flash on the cue that just went. The space bar also works as GO.
- **Timeline:** "Preview run" builds a `gsap.timeline()` with one label per cue and sequences through the whole list. It is visual only and writes nothing to the run log; when it ends, the board returns to the recorded state of the current run.
- `useGSAP` and `contextSafe` from `@gsap/react` scope the animations to the component so they are cleaned up on unmount.

## Not included

There is no deployment, no real-time sync between several operators, and no production hardening (the settings are for local development).
