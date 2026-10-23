## Signature database (magic bytes)

We recognize a file type by its **signature**: a sequence of bytes at a fixed position (offset) in the file.
Example: a PNG always starts with `89 50 4E 47 0D 0A 1A 0A`, and a TAR archive has the string
`ustar` at offset 257.

Signatures are kept in the `file_types` table. On first start the backend loads about
34 types from `backend/modules/filetypes_seed.py` into it and marks them as built-in (`builtin = true`).

### Signature fields

| Field | Meaning | Example |
|---|---|---|
| `name` | type name | `PNG image` |
| `extension` | extension (lowercase) | `png` |
| `magic` | signature in HEX | `89504E470D0A1A0A` |
| `offset` | where the signature lies in the file | `0` (TAR: `257`, MP4: `4`) |
| `scan_inside` | whether to also search for it **inside** other files (the "contains" relation) | `true` |
| `builtin` | a type from the initial database (read-only, set by the backend) | `true` / `false` |

### How recognition works

1. The backend reads the file header (the first 32,774 bytes, because ISO has `CD001` at offset 32769).
2. It checks signatures starting from the **longest**, so "JPEG EXIF" (`FFD8FFE1`) wins over the generic "JPEG" (`FFD8FF`).
3. The first match wins. When nothing matches, the type is unknown (`type: null`).

### Searching inside a file (`scan_inside`)

Signatures with `scan_inside = true` are searched for throughout the file. This reveals, for example, a ZIP appended
to the end of an image or an ELF program inside a firmware image.

- It only works for signatures of **≥ 4 bytes**. Shorter ones (e.g. `MZ` = `4D5A`) occur by chance
  in ordinary data and would produce lots of false hits. The API forces `false` here.
- At most 20 hits of one type per file.
- Every hit is **verified**: the signature must be followed by sensible header bytes
  (e.g. ELF: a valid class, byte order and version; Java class: version 45–80; ZIP: a known
  compression method). Without this, compressed data "contained" random ELFs and Java classes.
  The validators live in `VALIDATORS` in `backend/modules/features.py`. A custom signature without
  a validator is accepted without verification.
- Hits with the same extension as the file itself are skipped. Every ZIP entry starts
  with `PK\x03\x04`, so "ZIP contains ZIP" would be pure noise.

### Adding a custom signature

Via the API (takes effect immediately, no restart):

```bash
curl -X POST https://localhost/api/types -u admin:PASSWORD --cacert caddy-hex-root.crt \
  -H "X-Hex-Analyzer: 1" \
  -H "Content-Type: application/json" \
  -d '{"name": "My format", "extension": "myf", "magic": "4D 59 46 31", "offset": 0, "scan_inside": true}'
```

`magic` can be given in any HEX notation (`4D594631`, `4d 59 46 31`, `0x4D:59:46:31`).
It is stored as `4D594631`. Invalid HEX gives error 422.

- Replace `admin` with your login from `./caddy/set-password.sh`; the password is in `caddy/password.txt`.
- The `X-Hex-Analyzer` header (any value) is required on every `POST`/`DELETE` — without it 403 (CSRF protection).
- There can be at most `MAX_CUSTOM_TYPES` custom signatures (200 by default; each one slows down analysis) — beyond that 409.

List of signatures: `GET /api/types`.

### Deleting a custom signature

```bash
curl -X DELETE https://localhost/api/types/42 -u admin:PASSWORD --cacert caddy-hex-root.crt \
  -H "X-Hex-Analyzer: 1"
```

Response 204. A built-in signature cannot be deleted (403), and neither can a type that is assigned
to already analyzed files (409). Unknown `id` → 404.

To have the signature in every **new** database, also add it to `SEED_TYPES` in
`backend/modules/filetypes_seed.py`.

### Note

A new signature applies to files analyzed **after** it was added. Previously uploaded files
keep their old result until they are uploaded again.
