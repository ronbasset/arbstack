#!/bin/bash

# Setup for arbstack - Root User
set -e

echo "=== arbstack Setup Starting ==="

# Update system
apt update && apt upgrade -y

# Install dependencies
apt install -y python3.10 python3.10-venv python3-pip git tmux ufw curl jq

# Enable firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw --force enable

# Create trader user (if not exists)
if ! id "trader" &>/dev/null; then
    useradd -m -s /bin/bash trader
    usermod -aG sudo trader
    echo "trader ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
fi

# Clone repo to /opt (as root)
cd /opt
if [ ! -d "arbstack" ]; then
    git clone https://github.com/ronbasset/arbstack.git
fi
cd arbstack

# Setup Python environment
su - trader -c "
cd /opt/arbstack
python3.10 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install ccxt websockets pandas pyarrow prometheus-client pyyaml
"

# Create .env.example
cat > .env.example << 'EOF'
BINANCE_KEY=
BINANCE_SECRET=
KRAKEN_KEY=
KRAKEN_SECRET=
TRADING_ENABLED=false
ENV=prod
EOF

# Setup systemd service template
mkdir -p ops/systemd-templates
cat > ops/systemd-templates/arb-recorder.service << 'EOF'
[Unit]
Description=Arbstack Recorder
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/opt/arbstack
Environment=PATH=/opt/arbstack/venv/bin
ExecStart=/opt/arbstack/venv/bin/python src/apps/recorder.py --venue {{VENUE}} --pairs BTC,ETH,SOL
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "=== Setup Complete ==="
echo "Next: Edit /opt/arbstack/.env with your API keys"
echo "Then: su - trader && cd /opt/arbstack && source venv/bin/activate"
