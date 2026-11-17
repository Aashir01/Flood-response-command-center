#!/bin/bash
# Idempotent host setup for the Stitch VPS (deploy design 10; DEP-R6.3, R7.1). Run as root from
# a checkout of the repository:
#
#   PUBLIC_IP=203.0.113.7 DEPLOY_PUBKEY="ssh-ed25519 AAAA... github-actions-deploy" \
#     bash deploy/bin/vps_setup.sh
#
# What it does (and nothing else):
#   * user `deploy` (no password, no shell login: its key runs only the forced command);
#     not in the docker group; one sudo rule for /usr/local/bin/stitch-deploy
#   * installs stitch-deploy, stitch-check-dns, stitch-backup (root-owned, 0755)
#   * /opt/stitch/{prod.env,deploy.conf,backups} (prod.env 0600)
#   * UFW: allow 80/tcp, 443/tcp, 443/udp (22 stays as configured)
#   * cron: DNS check every 5 minutes, weekly pg_dump (Sunday 03:30 UTC)
#   * unattended security upgrades enabled
#   * sshd: keys only (no passwords); root keeps key login (the owner's access)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
STATE_DIR=/opt/stitch
ORIGIN_URL="${ORIGIN_URL:-/srv/stitch.git}"

[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }

# --- deploy user -------------------------------------------------------------------------------
if ! id deploy >/dev/null 2>&1; then
    adduser --disabled-password --gecos "Stitch CD (forced command only)" deploy
fi
passwd -l deploy >/dev/null
install -d -m 0700 -o deploy -g deploy /home/deploy/.ssh
if [[ -n "${DEPLOY_PUBKEY:-}" ]]; then
    opts='command="/usr/local/bin/stitch-deploy",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty'
    printf '%s %s\n' "$opts" "$DEPLOY_PUBKEY" > /home/deploy/.ssh/authorized_keys
    chown deploy:deploy /home/deploy/.ssh/authorized_keys
    chmod 0600 /home/deploy/.ssh/authorized_keys
fi
gpasswd -d deploy docker >/dev/null 2>&1 || true

# --- scripts and sudo rule ---------------------------------------------------------------------
install -m 0755 -o root -g root "$REPO/deploy/bin/deploy.sh" /usr/local/bin/stitch-deploy
install -m 0755 -o root -g root "$REPO/deploy/bin/check_dns.sh" /usr/local/bin/stitch-check-dns
install -m 0755 -o root -g root "$REPO/deploy/bin/backup.sh" /usr/local/bin/stitch-backup
rule='deploy ALL=(root) NOPASSWD: /usr/local/bin/stitch-deploy'
echo "$rule" > /etc/sudoers.d/stitch-deploy.tmp
chmod 0440 /etc/sudoers.d/stitch-deploy.tmp
visudo -cf /etc/sudoers.d/stitch-deploy.tmp >/dev/null
mv /etc/sudoers.d/stitch-deploy.tmp /etc/sudoers.d/stitch-deploy

# --- state directory ---------------------------------------------------------------------------
install -d -m 0750 -o root -g root "$STATE_DIR" "$STATE_DIR/backups"
if [[ ! -f "$STATE_DIR/prod.env" ]]; then
    install -m 0600 -o root -g root "$REPO/deploy/env/prod.env.example" "$STATE_DIR/prod.env"
fi
chmod 0600 "$STATE_DIR/prod.env"
if [[ ! -f "$STATE_DIR/deploy.conf" ]]; then
    cat > "$STATE_DIR/deploy.conf" <<EOF
# Read by stitch-deploy and stitch-check-dns (shell syntax).
ORIGIN_URL="$ORIGIN_URL"
PUBLIC_IP="${PUBLIC_IP:-}"
DOMAIN="stitch.aashirnoman.dev"
SMOKE_URL=http://127.0.0.1
SMOKE_ARGS="--allow-disabled voice"
BUILD_MISSING=1
EOF
    chmod 0644 "$STATE_DIR/deploy.conf"
fi

# --- firewall ----------------------------------------------------------------------------------
if command -v ufw >/dev/null 2>&1; then
    ufw allow 80/tcp >/dev/null
    ufw allow 443/tcp >/dev/null
    ufw allow 443/udp >/dev/null
fi

# --- cron --------------------------------------------------------------------------------------
cat > /etc/cron.d/stitch <<'EOF'
# Stitch (deploy/bin/vps_setup.sh)
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * root /usr/local/bin/stitch-check-dns >> /opt/stitch/dns.log 2>&1
30 3 * * 0 root /usr/local/bin/stitch-backup >> /opt/stitch/backup.log 2>&1
EOF
chmod 0644 /etc/cron.d/stitch

# --- sshd: keys only -----------------------------------------------------------------------------
# 05- sorts before cloud-init's 50-cloud-init.conf, and sshd uses the first value it reads.
cat > /etc/ssh/sshd_config.d/05-stitch-hardening.conf <<'EOF'
# Stitch VPS (deploy/README.md): keys only. Root keeps key login for the owner.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
sshd -t && systemctl reload ssh

# --- unattended security upgrades ----------------------------------------------------------------
if ! dpkg -s unattended-upgrades >/dev/null 2>&1; then
    apt-get install -y -q unattended-upgrades >/dev/null
fi
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

echo "vps_setup: ok (deploy user, scripts, /opt/stitch, ufw 80/443, cron, unattended-upgrades)"
