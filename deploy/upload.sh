#!/usr/bin/env bash
# Prenese trenutni kod (zadnji commit) na server i instalira/ažurira app.
# Pokretanje s računala (Git Bash):   bash deploy/upload.sh ubuntu@<JAVNA_IP_ADRESA_SERVERA>
# Za svako sljedeće ažuriranje: commitaj promjene i ponovno pokreni istu naredbu.
set -euo pipefail

TARGET="${1:?Upotreba: bash deploy/upload.sh ubuntu@<IP adresa servera>}"
ARCHIVE="$(mktemp -t padel-hunter-XXXX).tar.gz"

cd "$(dirname "$0")/.."
echo "==> Pakiram kod (git archive - samo commitane datoteke, bez data.db i tajni)"
git archive --format=tar.gz -o "$ARCHIVE" HEAD

echo "==> Šaljem na $TARGET"
scp -q -o StrictHostKeyChecking=accept-new "$ARCHIVE" "$TARGET:padel-hunter.tar.gz"
rm -f "$ARCHIVE"

echo "==> Raspakiravam i instaliram na serveru"
ssh -o StrictHostKeyChecking=accept-new "$TARGET" 'mkdir -p ~/padel-hunter && tar -xzf ~/padel-hunter.tar.gz -C ~/padel-hunter && rm ~/padel-hunter.tar.gz && bash ~/padel-hunter/deploy/server_install.sh'
