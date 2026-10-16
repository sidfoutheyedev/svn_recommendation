# SVN Recommender

Every product becomes 512 numbers (product_vector) from its picture and text (FashionCLIP).
Each user has one user_vector per category they follow.
Each feed: the 16 products closest to their user_vectors (max 6 of one style) + 4 random wildcards of their gender.

## Files

```
app/main.py         the API: /onboarding, /feed, /reset, /health
app/recommend.py    onboarding, learning from swipes, building the feed
app/database.py     all the SQL
app/config.py       all the settings (styles, 16 + 4 cards, weights...)
schema.sql          the 4 tables: products, users, user_vectors, feed_log (interaction log)
embedding_job.py    run daily at 4 AM: adds, updates and removes products from the CSV
download_model.py   run once per machine
check_vectors.py    proof: python check_vectors.py SOULED_279325
```

Categories come from the CSV, so new categories work automatically. Styles are fixed in `app/config.py`.

## Project setup

Use Python 3.11.9 or 3.11.x.

### 1) Create a virtual environment

```bash
cd /path/to/svn-recommender
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

On AWS or CPU-only environments, use:

```bash
pip install torch==2.2.2 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

### 3) Configure environment variables

```bash
cp .env.example .env
```

Then update `.env` with:

```env
DATABASE_URL=postgresql://user:password@host:5432/dbname
PRODUCTS_CSV=http://your_csv_link
```

`PRODUCTS_CSV` can also be a local file path for testing.

### 4) Download the model

```bash
python download_model.py
```

This downloads FashionCLIP into `models/fashion-clip`.

### 5) Create database tables

The app creates tables automatically on startup, but if you want to initialize manually first:

```bash
python - <<'PY'
from app import database
from app import config

database.create_tables()
print('tables ready')
PY
```

### 6) Run the recommender job and API

```bash
python embedding_job.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The app is available at:

```text
http://localhost:8000/health
```

### Docker setup

Build and run with Docker:

```bash
docker build -t svn-recommender .
docker run --rm --name svn-recommender -p 8000:8000 --env-file .env svn-recommender
```

Or with Docker Compose:

```bash
docker compose up --build -d
```

Postgres needs the pgvector extension (AWS RDS has it).

## Run (always from this folder)

```
python download_model.py
python embedding_job.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 4 AM job (cron, server clock in UTC: 22:30 UTC = 4:00 AM India)

```
30 22 * * * cd /home/ubuntu/svn-recommender && venv/bin/python embedding_job.py >> logs/job.log 2>&1
```

No API restart needed. Each run writes `reports/embedding_job_<date>.csv` with every product that was
added, re-embedded, updated, removed, inactive, skipped (bad values) or failed (tried again next run).
Every product is checked and saved on its own, so one bad row never affects the rest of the table.
The job stops without changing anything only if the CSV can't be read, a column is missing, or no rows are clean.

## API

- `POST /onboarding` `{"user_id": "u1", "gender": "male", "categories": ["casual", "formal"]}`
- `POST /feed` `{"user_id": "u1", "interactions": [{"product_id": "SOULED_279325", "action": "like"}]}`
  (action: like, dislike, add_to_cart. Send the swipes since the last call.)
- `POST /reset` `{"user_id": "u1"}` forgets what the user has seen, keeps their user_vectors
- `GET /health`

Answer: `{"products": [{"product_id", "category", "style", "source", "score"}, ...], "exhausted": false}`.
`exhausted: true` (empty list) = the user has seen everything: show a message or call `/reset`.
Errors: 400 wrong value, 404 user not onboarded, 422 missing field, 503 database down.
