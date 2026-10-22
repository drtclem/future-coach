#!/usr/bin/env bash
# One-time setup of a fresh Ubuntu 24.04 droplet. Run from your Mac:
#   ssh root@<IP> 'bash -s' -- "$(cat ~/.ssh/future_coach_deploy.pub)" < scripts/bootstrap.sh
# Safe to re-run. Prints the dashboard login once (only when it creates it).
set -euo pipefail
DEPLOY_PUBKEY="$*"  # ssh joins remote args with spaces, so the key arrives as 3 words
case "$DEPLOY_PUBKEY" in "ssh-ed25519 "*" "*) ;; *) echo "pass the full deploy public key (type, key, comment)"; exit 1;; esac
IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
HOST="${IP//./-}.sslip.io"  # free DNS name that resolves to the IP, so Caddy can get a real certificate

export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q python3 python3-venv ufw caddy rsync curl

# deploy user: CI logs in as this user and may only restart the app
id deploy >/dev/null 2>&1 || adduser --disabled-password --gecos "" deploy
usermod -aG systemd-journal deploy  # lets a failed deploy print the app log
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
echo "$DEPLOY_PUBKEY" > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys && chmod 600 /home/deploy/.ssh/authorized_keys
cat > /etc/sudoers.d/future-coach <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart future-coach
EOF
chmod 440 /etc/sudoers.d/future-coach

# SSH: keys only (root keeps key login so you are never locked out)
echo "PasswordAuthentication no" > /etc/ssh/sshd_config.d/00-keys-only.conf  # 00- wins over cloud-init's 50- file
systemctl reload ssh

# firewall: SSH + HTTP(S) only; the app itself listens on localhost
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

# app dirs: code (deployed by CI), runtime data, secrets
install -d -o deploy -g deploy /opt/future_coach /var/lib/future_coach
if [ ! -f /etc/future_coach.env ]; then
  cat > /etc/future_coach.env <<'EOF'
# Normally empty: CI deploys the keys to /var/lib/future_coach/ci.env. Values here are a manual fallback.
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://us.cloud.langfuse.com
EOF
fi
chown root:deploy /etc/future_coach.env && chmod 640 /etc/future_coach.env

cat > /etc/systemd/system/future-coach.service <<'EOF'
[Unit]
Description=Future Coach
After=network.target

[Service]
User=deploy
WorkingDirectory=/opt/future_coach/backend
EnvironmentFile=/etc/future_coach.env
# written by the CI deploy job from the GitLab variables (overrides the file above)
EnvironmentFile=-/var/lib/future_coach/ci.env
Environment=FC_EVENTS_PATH=/var/lib/future_coach/events.jsonl
ExecStart=/opt/future_coach/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable future-coach  # starts after the first deploy puts code in place

# HTTPS + one coach login in front of everything (basicauth: Ubuntu 24.04 ships Caddy 2.6, before the basic_auth spelling)
if ! grep -q basicauth /etc/caddy/Caddyfile 2>/dev/null; then
  PASS=$(head -c 18 /dev/urandom | base64 | tr -d '/+=')
  HASH=$(caddy hash-password --plaintext "$PASS")
  cat > /etc/caddy/Caddyfile <<EOF
$HOST {
	basicauth {
		coach $HASH
	}
	reverse_proxy 127.0.0.1:8000
}
EOF
  systemctl reload caddy
  echo
  echo "Dashboard: https://$HOST"
  echo "Login:     coach / $PASS   (shown once; save it in your password manager)"
fi
[ -x /opt/future_coach/.venv/bin/uvicorn ] && systemctl restart future-coach  # re-run: pick up unit changes
echo "Bootstrap done."
