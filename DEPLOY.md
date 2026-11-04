# Deploying the demo

Status: the pieces below are tested locally (download, checksum, unpack, rate limit, app).
Last full local rehearsal: 2026-11-05. The serving database was rebuilt from the current pramaan.db
(327 MB gzipped, 1.35 GB unpacked, sha256 in dist/pramaan-serving.sha256), served from a local
web server, fetched and verified by the app on first start, and answered a 6-citation draft
with the same statuses as the full database.
The Dockerfile has NOT been built (Docker is not installed on the dev machine) and nothing has
been published. Do the checks at the end before making anything public.

## 1. Build the serving database
    uv run python scripts/build_serving_db.py     # dist/pramaan-serving.db.gz (327 MB) + .sha256

## 2. Host the file
Upload `dist/pramaan-serving.db.gz` somewhere with a stable public URL, for example a public
Hugging Face dataset repo. The data is derived from the CC-BY-4.0 Supreme Court dataset:
credit the source in that repo's README.

## 3. Run the container (any host; Hugging Face Spaces "Docker" uses port 7860)
    docker build -t pramaan .
    docker run -p 7860:7860 \
      -e PRAMAAN_DB_URL=https://.../pramaan-serving.db.gz \
      -e PRAMAAN_DB_SHA256=$(cat dist/pramaan-serving.sha256) pramaan

On first start the app downloads, verifies and unpacks the database into /data. Free hosts wipe
the disk on restart, so expect the download again after each restart.
Do not set PRAMAAN_ENABLE_LLM on a public host unless you have a model for it to call.

## Running it
Use ONE worker process (`uvicorn ... --workers 1`, the default). The rate limiter keeps its counts in
memory, so several workers would each allow the full number of uploads. Checks run in a thread pool,
so a slow request does not block the others. The app opens the database read-only, one connection
per request. Expect about 1.4 GB of disk for the database plus the 327 MB download while unpacking.
Not measured: memory use of the running app, sustained load, behaviour behind a real proxy.

## Settings
| Variable | Meaning |
|---|---|
| PRAMAAN_DB_URL, PRAMAAN_DB_SHA256 | where to fetch the database, and its checksum |
| PRAMAAN_DB_PATH | where to keep it (default pramaan.db; /data/pramaan.db in the image) |
| PRAMAAN_ENABLE_LLM=1 | allow the optional AI support check |
| PRAMAAN_JUDGE_BACKEND / _MODEL, PRAMAAN_OLLAMA_URL, PRAMAAN_OPENAI_URL | judge model settings |

## Before it goes public
1. Employment IP clause cleared (SPEC section 11).
2. Resolver test split run once, README numbers final.
3. The page says "Preview" and states that accuracy is still being measured.
4. A real draft tested end to end, including footnotes from a file saved by Word.
5. Free-host terms checked: Hugging Face Docker Spaces may need a paid plan.
