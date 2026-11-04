# Running the demo on an Oracle Cloud Always Free VM

Status: written 2026-11-05, NOT yet tried on a real Oracle VM. The Docker image has never been built
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
