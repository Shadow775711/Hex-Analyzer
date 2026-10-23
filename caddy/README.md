# Caddy — HTTPS + password

Caddy sits in front of the application: it serves HTTPS from its own CA (`tls internal`),
requires a login (`basic_auth`), redirects HTTP → HTTPS and adds security headers.

## First start

```bash
# 1. addresses the application should answer on (the certificate is issued for them)
cp .env.example .env        # and fix the IP address

# 2. login and password (login "admin" by default)
./caddy/set-password.sh

# 3. start
docker compose up -d
```

Local files (in `.gitignore`, never commit them):

| File | Content |
|---|---|
| `caddy/password.txt` | the password in plain text (mode 600) — so you can look it up; **not** mounted into the container |
| `caddy/auth.caddy` | login + bcrypt hash of the password — the only file Caddy gets; mode 644 because Caddy runs without capabilities and cannot bypass file permissions (a hash of a random ~130-bit password is not crackable) |
| `.env` | `HEX_HOSTS`, `HEX_DEFAULT_SNI`, `HEX_BIND` |

`docker compose up` refuses to start if `caddy/auth.caddy` is missing — run `set-password.sh` first.

The password is random (~130 bits), so the script uses bcrypt cost 10: a higher cost would add
no protection, only make every failed login burn ~1 s of CPU (an easy denial of service).
It is passed to `caddy hash-password` through stdin, never on the command line.

## CA certificate

The browser does not know Caddy's CA, so it shows a warning until you import it:

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-hex-root.crt
```

- Firefox: Settings → Privacy & Security → Certificates → View Certificates →
  Authorities → Import → tick "Trust this CA to identify websites".
- Android: Settings → Security → Encryption & credentials → Install a certificate → CA certificate.

Don't delete the `caddy_data` volume — a new CA would have to be imported again on every device.

## Who can reach it (`HEX_BIND`)

Docker publishes ports past the host firewall, so the listening address matters:

| `HEX_BIND` | Reachable from |
|---|---|
| `127.0.0.1` (default) | this computer only |
| your LAN IP, e.g. `192.168.1.50` | this computer and your local network; Caddy won't start if the IP changes |
| `0.0.0.0` | every network the computer joins — including public Wi-Fi |

## Access by IP address

The browser sends no server name (SNI) when connecting to an IP address, so
`HEX_DEFAULT_SNI` tells Caddy which certificate to serve by default. Server IP changed →
fix `.env` and run `docker compose up -d caddy`.

## Changing the configuration

Caddy does not pick up changes to `Caddyfile` or `auth.caddy` on its own — after editing:

```bash
docker compose restart caddy
```
