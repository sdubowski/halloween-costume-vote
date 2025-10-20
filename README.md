
# Halloween Party Voting — Single QR + Waiting Room (Flask)

A Flask app for a Halloween party:
- Admin creates an event, sets **expected players** (number of participants).
- One **join link / QR** per event.
- Each participant registers (name + photo).
- Everyone lands in a **waiting room** showing `joined/expected`.
- **Voting opens automatically** when everyone has joined.
- One vote per participant; can't vote for yourself.
- Live results page.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```
App: http://127.0.0.1:5000

## ngrok (public access)
```bash
ngrok http 5000
```
Open the **ngrok URL** in your browser and create the event **there** so QR uses the public domain.

## Notes
- SQLite DB at `instance/app.db`.
- Photos saved under `static/uploads/`, QR codes in `static/qrs/`.
- On schema changes (e.g., added `expected_players`), delete `instance/app.db` to recreate tables (or use Alembic migrations).
- For production: use a managed DB (Postgres) and object storage for photos (S3/Spaces).
