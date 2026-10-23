#!/usr/bin/env sh
# Creates (or changes) the login and password for the application.
#   ./caddy/set-password.sh            → login "admin", random password
#   ./caddy/set-password.sh jan        → login "jan", random password
# The password goes to caddy/password.txt (for you only, mode 600), and Caddy gets
# only its hash (caddy/auth.caddy). Both files are in .gitignore; only auth.caddy is
# mounted into the Caddy container.
set -eu

LOGIN="${1:-admin}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CADDY_IMAGE="caddy:2.11.7@sha256:504a44d7d74bd2bc28a66afc4774912fc21223ca8a67734af1c54ab2f999b489"

case "$LOGIN" in
  *[!A-Za-z0-9._-]*|"") echo "Login: letters, digits, . _ - only" >&2; exit 1 ;;
esac

umask 077
PASS="$(head -c 18 /dev/urandom | base64 | tr -d '/+=')"
# The password goes through stdin, not the command line (visible to other users in `ps`).
# bcrypt cost 10: the password is random (~130 bits), so a high cost adds no protection —
# it would only make every failed login burn ~1 s of CPU (an easy DoS).
HASH="$(printf '%s\n' "$PASS" | docker run --rm -i "$CADDY_IMAGE" caddy hash-password --algorithm bcrypt --bcrypt-cost 10)"

# written in place (same inode): Caddy mounts auth.caddy as a single file, and a deleted and
# recreated file would stay invisible to the running container
printf '%s\n' "$PASS" > "$DIR/password.txt"
printf 'basic_auth {\n\t%s %s\n}\n' "$LOGIN" "$HASH" > "$DIR/auth.caddy"
chmod 600 "$DIR/password.txt"
# auth.caddy must be world-readable: Caddy runs as root but WITHOUT capabilities (cap_drop: ALL),
# so it cannot bypass file permissions. It holds only the bcrypt hash of a random ~130-bit
# password, which is not crackable — the plaintext password.txt stays private (600).
chmod 644 "$DIR/auth.caddy"

echo "Login: $LOGIN — password saved to caddy/password.txt"
cd "$DIR/.."   # docker compose needs the project directory
if docker compose ps --status running caddy 2>/dev/null | grep -q caddy; then
  # recreate rather than restart, so the container is guaranteed to see the current file
  docker compose up -d --force-recreate caddy >/dev/null 2>&1 && echo "Caddy reloaded."
fi
