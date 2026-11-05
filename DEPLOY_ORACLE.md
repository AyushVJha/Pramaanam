# Running the demo on an Oracle Cloud Always Free VM

Status: the Docker route below is still untried. What actually runs (2026-11-05) is described in the
section "What is actually deployed" at the end.

Original status line: written 2026-11-05, NOT yet tried on a real Oracle VM. The Docker image has never been built
(no Docker on the dev machine), and Oracle's current free limits were not confirmed (sources
disagree). Do the steps in order and stop at the first surprise.

## 0. What you need
- An Oracle Cloud account (needs a card at signup; you pay nothing inside the free limits).
- The serving database uploaded somewhere public (step 2).

## 1. Create the VM (Oracle console, you do this)
- Region: Mumbai (ap-mumbai-1) if it has capacity; otherwise Hyderabad or Singapore.
- Image: Ubuntu 22.04 or 24.04. Shape: an Always Free one (Ampere A1 "VM.Standard.A1.Flex" 2 to 4 OCPU,
  12 to 24 GB RAM, or the free AMD micro shape if A1 is out of capacity; the micro has 1 GB RAM, which is
  tight but the app uses about 280 MB). Boot volume 50 GB or more (the database is 1.9 GB).
- Add your SSH public key. Note the public IP.
- In the VM's subnet security list (or network security group) allow inbound TCP 80 and 443
  (and 22 for SSH, which is on by default).
- Oracle idle rule: free instances with very low use can be reclaimed. Many people upgrade the account to
  "Pay As You Go" (still free inside the limits) to avoid this; not verified here. Check the console.

## 2. Put the database file somewhere public (on your laptop)
    uv run python scripts/build_serving_db.py      # dist/pramaan-serving.db.gz and .sha256
Upload `dist/pramaan-serving.db.gz` to a public place with a stable URL (a Hugging Face dataset repo is
fine; credit the CC-BY-4.0 source in its README). Keep `dist/pramaan-serving.sha256` (the app refuses a
file whose checksum differs).

## 3. Prepare the server (over SSH)
    sudo apt-get update && sudo apt-get install -y docker.io docker-compose-v2 git
    sudo usermod -aG docker $USER      # log out and back in once
    sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
    sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT   # Ubuntu images on Oracle block these by default
(The iptables lines are not saved across reboots; install `iptables-persistent` if you want them kept.)

## 4. Get the code and start it
    git clone <your repo URL> pramaan && cd pramaan/deploy
    cp .env.example .env && nano .env      # fill in the database URL and checksum
    docker compose up -d --build           # first build takes several minutes
    docker compose logs -f app             # wait for "database ready" / "Application startup complete"
The app downloads and unpacks the database on first start (439 MB download, 1.9 GB on disk) into the
`pramaan-data` volume, so later restarts are fast.

## 5. Check it
    curl http://<server-ip>/health          # {"status":"ok","database":true}
Open http://<server-ip>/ and check a draft with `demo/mixed_draft.txt`. The page says "Preview".
For HTTPS, point a hostname at the IP (a free DNS name works), set SITE_ADDRESS to that hostname in
`.env`, and run `docker compose up -d` again; Caddy gets the certificate itself.

## 6. Updating and recovering
- Update the code: `git pull && docker compose up -d --build`.
- New database: change PRAMAAN_DB_URL and PRAMAAN_DB_SHA256, then `docker compose down`,
  `docker volume rm deploy_pramaan-data`, `docker compose up -d`.
- If the VM is lost: repeat steps 1, 3 and 4 on a new one. Nothing else is stored on it.

## Not measured / not done
Build time on ARM, memory under load on a 1 GB shape, behaviour behind Caddy, whether Oracle reclaims
an idle instance, uptime. Keep the paid VPS option (DEPLOY.md) as the fallback.

## What is actually deployed (2026-11-05)
- Hyderabad (ap-hyderabad-1) had no free ARM capacity ("Out of host capacity" for A1.Flex), so the server is
  the free AMD shape VM.Standard.E2.1.Micro: 1 OCPU, 956 MB RAM, 50 GB disk, Ubuntu 22.04. Created with the
  OCI command-line tool (`oci session authenticate`, then `oci compute instance launch`).
- No Docker (building images on 1 GB is fragile). The app runs from `/opt/pramaan` with `uv sync --python 3.12`,
  as a systemd service (`deploy/native/pramaan.service`, memory capped at 700 MB), behind Caddy on port 80
  (`deploy/native/Caddyfile`). A 2 GB swap file was added. Ports 80 and 443 were opened in the VCN security
  list and in the server's iptables (saved with iptables-persistent).
- The serving database was copied straight from the laptop with rsync (no public upload), its SHA-256 checked
  against `dist/pramaan-serving.sha256`, then unpacked to `/opt/pramaan/data/pramaan.db`.
- Checked from outside: `/health` returns ok, and `demo/mixed_draft.txt` returns the expected statuses.
- Not done: HTTPS (needs a hostname), a retry for the bigger ARM shape, any monitoring or backups,
  a test of a reboot, and a measurement of speed and memory under several simultaneous users.
- Update the code: `rsync` the `src/` folder again, then `sudo systemctl restart pramaan`.
- Hostnames (2026-11-05): `pramaanam.duckdns.org` (free DuckDNS name, pointing at the server's IP) and
  `129-225-90-183.sslip.io` (free, no signup). Caddy obtains and renews the HTTPS certificates for both by
  itself. The public IP is an ordinary one, not reserved: if the instance is deleted and recreated, update
  the DuckDNS entry and the sslip.io name in `/etc/caddy/Caddyfile`. A real domain, when bought, needs
  an A record to the server's IP and one more name in that file.

## Update 2026-11-05: later-treatment flags deployed
- New serving database (419 MB gz, sha256 `c5c93245485008481805c042fe18d2b4af62db3d875e2c3873a518b98807e342`)
  uploaded with rsync, checksum verified on the server, unpacked to `pramaan.db.new`, then swapped in
  (`pramaan.db` -> `pramaan.db.old`, `pramaan.db.new` -> `pramaan.db`) and the service restarted
  (about a minute of downtime). The `src/` folder was synced in the same step.
- Checked from outside: `/health` ok; a citation to ADM Jabalpur returns NEEDS_REVIEW naming Puttaswamy (2017);
  `demo/mixed_draft.txt` returns the same mix of statuses as before.
- Rollback: `cd /opt/pramaan/data && mv pramaan.db pramaan.db.bad && mv pramaan.db.old pramaan.db &&
  sudo systemctl restart pramaan` (the old code is compatible: it ignores the extra table).
- `pramaan.db.old` (1.8 GB) can be deleted once you are happy; the 50 GB disk has room.
- The agents are still NOT enabled on the server.

## Update 2026-11-05: AI reading check enabled on the live site (opt-in, experimental)
- A visitor must tick "AI reading check (experimental)"; the box says what is sent where: the sentence around each
  checked citation and paragraphs of the matched judgment go to Google's Gemini API (free tier; Google may use
  inputs to improve its models). Off by default. It can only add warnings, never a green tick.
- Limits per request: 4 citations, 5 steps and 50 s per citation, 150 s in all; one agent job at a time on the server
  (a second visitor is told "busy"); `cache=False`, so no model reply is written to disk. The usage log keeps token
  counts and the model name only: a first version also logged the model's reply text, which could echo a
  visitor's draft; that was found the same day, fixed (`keep_text` is off when `cache=False`), and the log was wiped.
- Server config: `/etc/pramaan-agents.env` (root-only, holds the API key and `PRAMAAN_ENABLE_AGENTS=1`,
  `PRAMAAN_LLM_RETRIES=2`) loaded by a systemd drop-in `/etc/systemd/system/pramaan.service.d/agents.conf`.
  The key is not in git. To turn the agents off: remove `PRAMAAN_ENABLE_AGENTS` from that file and
  `sudo systemctl restart pramaan`.
- Model: `gemini-3.1-flash-lite`. `gemini-3.5-*` models were rejected by Gemini's function-call filter or timed out
  when tested; larger Flash models often answered "high demand".
- Not measured: accuracy of the agent on the v2 benchmark (the free tier was too unreliable during the run), and
  how the free tier behaves under many simultaneous visitors.
