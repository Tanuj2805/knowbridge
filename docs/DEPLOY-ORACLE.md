# Deploying KnowBridge on Oracle Cloud (free)

One free Oracle server runs everything: the website, the API, the worker, Postgres and OpenFGA,
behind Caddy for HTTPS. About an hour the first time. Commands in grey boxes are copy and paste.

**What you need:** an Oracle Cloud account (Always Free), a GitHub account with access to this
repository, and Windows PowerShell (or any terminal).

---

## 1. Create the server

In the Oracle console: **☰ → Compute → Instances → Create instance**.

| Setting | Value |
|---|---|
| Name | `knowbridge` |
| Image | **Canonical Ubuntu 24.04** |
| Shape | **Ampere → VM.Standard.A1.Flex**, **2 OCPUs, 12 GB memory** (stays within Always Free) |
| Networking | the default new network, **Assign a public IPv4 address: on** |
| SSH keys | **Generate a key pair for me**, then **download the private key** |
| Boot volume | default (about 50 GB) |

Click **Create** and wait for **Running**. Copy the **Public IP address**.

> "Out of capacity"? Try another *Availability domain* on the same page, or 1 OCPU / 6 GB, or try
> again later. It is common and not a rejection.

**Safety net:** ☰ → Billing & Cost Management → **Budgets → Create budget**, amount `1`, alert on
actual spend above 1%. You get an email if anything ever costs money.

## 2. Open the web ports (two places)

**a) In Oracle:** on the instance page, click the **Subnet** link → **Security Lists** → the default
list → **Add Ingress Rules**, twice:

| Source CIDR | Protocol | Destination port |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

**b) On the server itself** — Oracle's Ubuntu images also block these ports. You'll do this in step 4.

## 3. Connect to the server

In PowerShell on your laptop (replace the key file name and the IP):

```powershell
# once: the key must be readable only by you
icacls "$HOME\Downloads\ssh-key-2026-11-10.key" /inheritance:r /grant:r "$($env:USERNAME):R"

ssh -i "$HOME\Downloads\ssh-key-2026-11-10.key" ubuntu@<PUBLIC_IP>
```

Type `yes` the first time. You're in when the prompt says `ubuntu@knowbridge`.

## 4. Prepare the server (copy the whole block)

```bash
# updates, firewall ports 80/443, and Docker
sudo apt-get update && sudo apt-get -y upgrade
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p udp --dport 443 -j ACCEPT
sudo netfilter-persistent save
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
# a little swap, so building the website never runs out of memory
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
exit
```

Connect again (`ssh -i ... ubuntu@<PUBLIC_IP>`) so the Docker permission takes effect.

## 5. Get a free domain

1. Go to **duckdns.org**, sign in with GitHub or Google.
2. Add a subdomain, e.g. `knowbridge` → you get `knowbridge.duckdns.org`.
3. Put the server's **Public IP** in the *current ip* box → **update ip**.

(A paid domain works the same: add an **A record** pointing to the Public IP.)

## 6. Get the code onto the server

The repository is private, so give the server a read-only key:

```bash
ssh-keygen -t ed25519 -N "" -f ~/.ssh/github -C knowbridge-server
cat ~/.ssh/github.pub
```

On GitHub: **repository → Settings → Deploy keys → Add deploy key**, paste the line, leave
*write access* off. Then:

```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/github\n' >> ~/.ssh/config
git clone git@github.com:Tanuj2805/knowbridge.git
cd knowbridge
```

## 7. Settings

```bash
cp .env.production.example .env
openssl rand -base64 48   # run 3 times: for POSTGRES_PASSWORD, API_JWT_SECRET, AUTH_SECRET
docker run --rm python:3.12-slim python -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"   # SECRETS_KEY
nano .env
```

Fill in `DOMAIN`, `WEB_URL`, the secrets, and **new** AI keys (rotate the ones used during
development). Save with `Ctrl+O`, `Enter`, exit with `Ctrl+X`.

## 8. Sign-in (GitHub and/or Google)

Judges and teammates sign in with their own account; the "sign in as a teammate" buttons only
exist on a developer's laptop.

**GitHub:** github.com → Settings → Developer settings → **OAuth Apps → New OAuth App**
- Homepage URL: `https://<your-domain>`
- Authorization callback URL: `https://<your-domain>/api/auth/callback/github`
- Copy the **Client ID** and a new **Client secret** into `AUTH_GITHUB_ID` / `AUTH_GITHUB_SECRET`.

**Google (optional):** console.cloud.google.com → APIs & Services → Credentials → **OAuth client ID**
(Web application), redirect URI `https://<your-domain>/api/auth/callback/google` → copy into
`AUTH_GOOGLE_ID` / `AUTH_GOOGLE_SECRET`.

## 9. Start KnowBridge

```bash
docker compose -f compose.yaml -f compose.prod.yaml up -d --build
```

The first build takes 5–10 minutes. Then check:

```bash
docker compose -f compose.yaml -f compose.prod.yaml ps      # every service "running" / "healthy"
docker compose -f compose.yaml -f compose.prod.yaml logs -f caddy   # look for "certificate obtained"
```

Open **https://&lt;your-domain&gt;** — the home page with the walkthrough video should load, with a
padlock. Sign in, then **Projects → New project → Load the demo** for Project Nimbus.

## 10. Daily backups

```bash
mkdir -p ~/backups && chmod +x infra/backup.sh && ./infra/backup.sh
(crontab -l 2>/dev/null; echo "30 3 * * * $PWD/infra/backup.sh >> $HOME/backups/backup.log 2>&1") | crontab -
```

---

## Everyday commands (run inside `~/knowbridge`)

| To | Run |
|---|---|
| Update to the latest code | `git pull && docker compose -f compose.yaml -f compose.prod.yaml up -d --build` |
| See what's running | `docker compose -f compose.yaml -f compose.prod.yaml ps` |
| Follow the logs | `docker compose -f compose.yaml -f compose.prod.yaml logs -f api worker` |
| Restart everything | `docker compose -f compose.yaml -f compose.prod.yaml restart` |
| Memory and CPU | `docker stats --no-stream` |

Tip: `alias kb='docker compose -f compose.yaml -f compose.prod.yaml'` in `~/.bashrc` turns all of
these into `kb ps`, `kb logs -f api`, and so on.

## If something goes wrong

| Problem | Fix |
|---|---|
| Site doesn't open at all | Ports 80/443 not open: redo step 2a and the `iptables` lines in step 4 |
| "certificate" errors in `logs caddy` | The domain doesn't point at the server yet (check DuckDNS), or ports are closed |
| Sign-in fails with "redirect_uri" | The OAuth callback URL must match your domain exactly (step 8) |
| "Build claims" never finishes | `logs -f worker`; usually an AI key problem or its quota |
| Server was reclaimed or stopped | Oracle can stop idle Always Free servers; start it from the console. Data stays on the disk |
