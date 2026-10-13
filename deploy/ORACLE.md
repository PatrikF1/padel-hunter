# Padel Hunter na Oracle Cloud serveru (besplatno, 0–24 h)

Kad je app na serveru, radi i kad je računalo ugašeno: pretraga s iPhonea s bilo kojeg mjesta,
praćenje i Telegram obavijesti 0–24 h. App vide **samo tvoji uređaji** (Tailscale), a port nije
otvoren prema internetu.

```
Oracle server (Frankfurt) ── Tailscale ── iPhone (ikona na početnom zaslonu)
                                     └── računalo (za ažuriranja)
```

## 1. SSH ključ na računalu (jednom)
SSH ključ je "ključ od servera". U Git Bashu ili PowerShellu:

```bash
ssh-keygen -t ed25519 -C padel-hunter
```

Samo pritišći Enter (zadana mjesta). Javni dio ključa ispiši ovako i kopiraj cijeli redak:

```bash
cat ~/.ssh/id_ed25519.pub
```

## 2. Server u Oracle konzoli
cloud.oracle.com → izbornik ☰ → **Compute → Instances → Create instance**
- **Name:** `padel-hunter`
- **Image:** Change image → **Canonical Ubuntu 24.04**
- **Shape:** Change shape → **Ampere → VM.Standard.A1.Flex**, 1 OCPU, 6 GB (oznaka *Always Free-eligible*)
  - ako javi *Out of capacity*: probaj ponovno kasnije, ili odaberi **AMD → VM.Standard.E2.1.Micro** (također besplatan, slabiji, ali dovoljan)
- **Add SSH keys:** *Paste public keys* → zalijepi redak iz koraka 1
- **Create**, pričekaj status *Running* i kopiraj **Public IP address**

Port 8777 **ne otvaraj** u Oracle mreži (Security List). Nije potrebno, jer promet ide kroz Tailscale.

## 3. Instalacija (s računala, jedna naredba)
U Git Bashu, u mapi projekta:

```bash
bash deploy/upload.sh ubuntu@<PUBLIC_IP>
```

Skripta pri prvom spajanju sama prihvati ključ novog servera.

## 4. Tailscale na serveru (jednom)

```bash
ssh ubuntu@<PUBLIC_IP>
sudo tailscale up
```

Otvori link koji ispiše i prijavi se **istim Tailscale računom** kao na iPhoneu. Server se sad
vidi u Tailscale aplikaciji (npr. `padel-hunter`, adresa `100.x.y.z`).

## 5. iPhone
1. App Store → **Tailscale**, prijava istim računom, uključi VPN.
2. Safari → `http://100.x.y.z:8777` (adresa servera iz Tailscale aplikacije).
3. **Dijeli → Dodaj na početni zaslon** → ikona Padel Hunter.
4. U appu **Postavke → Telegram** ponovno poveži bota (server ima svoju bazu).

## Ažuriranje
Nakon promjena u kodu: `git commit`, pa ponovno `bash deploy/upload.sh ubuntu@<PUBLIC_IP>`.
Podaci na serveru (praćenja, Telegram, katalog) ostaju.

## Kad nešto ne radi
| Problem | Naredba (na serveru, `ssh ubuntu@<PUBLIC_IP>`) |
|---|---|
| radi li app? | `systemctl status padel-hunter` |
| greške uživo | `journalctl -u padel-hunter -f` |
| restart | `sudo systemctl restart padel-hunter` |
| je li Tailscale spojen? | `tailscale status` |

**Oracle može ugasiti besplatni server koji je "previše besposlen"** (vrlo malo opterećenja 7 dana).
To sprječava nadogradnja računa na **Pay As You Go** (Billing → Upgrade): i dalje je besplatno unutar
Always Free granica, ali to pravilo više ne vrijedi. Preporučeno nakon što sve proradi.
