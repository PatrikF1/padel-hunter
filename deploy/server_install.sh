#!/usr/bin/env bash
# Instalacija / ažuriranje Padel Huntera na Ubuntu serveru (Oracle Cloud). Pokreće ga deploy/upload.sh.
# Smije se pokretati više puta: postojeći podaci (data.db, catalog.json) i .venv ostaju.
set -euo pipefail

APP_DIR="$HOME/padel-hunter"
SERVICE=padel-hunter
cd "$APP_DIR"

echo "==> 1/4 Sistemski paketi (Python)"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip curl >/dev/null

echo "==> 2/4 Python okruženje i paketi"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> 3/4 Servis (pokreće se sam nakon restarta servera, i ponovno ako se sruši)"
sudo tee /etc/systemd/system/$SERVICE.service >/dev/null <<EOF
[Unit]
Description=Padel Hunter
After=network-online.target tailscaled.service
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now $SERVICE >/dev/null
sudo systemctl restart $SERVICE

echo "==> 4/4 Tailscale (app je dostupan SAMO tvojim uređajima, port nije otvoren prema internetu)"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
# Oracle Ubuntu slike odbijaju sav ulazni promet osim SSH-a - dopusti promet koji dolazi kroz Tailscale
sudo iptables -C INPUT -i tailscale0 -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 -i tailscale0 -j ACCEPT
sudo ip6tables -C INPUT -i tailscale0 -j ACCEPT 2>/dev/null || sudo ip6tables -I INPUT 1 -i tailscale0 -j ACCEPT
command -v netfilter-persistent >/dev/null && sudo netfilter-persistent save >/dev/null 2>&1 || true

echo
if tailscale ip -4 >/dev/null 2>&1; then
  echo "GOTOVO. Na iPhoneu (s upaljenim Tailscaleom) otvori:  http://$(tailscale ip -4 | head -1):8777"
else
  echo "GOTOVO. Još jedan korak: pokreni   sudo tailscale up   i otvori link koji ispiše (prijava u Tailscale)."
fi
echo "Logovi:  journalctl -u $SERVICE -f        Restart:  sudo systemctl restart $SERVICE"
