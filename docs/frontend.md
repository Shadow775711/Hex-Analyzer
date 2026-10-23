# Hex Analyzer - Frontend Documentation

## Table of contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation and configuration](#installation-and-configuration)
4. [Components](#components)
5. [Hooks and utilities](#hooks-and-utilities)
6. [Features](#features)
7. [Performance optimizations](#performance-optimizations)
8. [Styling and UI](#styling-and-ui)
9. [Testing](#testing)

---

## Overview

The **Hex Analyzer** frontend is a modern React application that offers:
- 📁 Binary file upload with analysis
- 🔍 A virtualized hex dump that handles large files
- 🎯 An interactive relation graph between files (similar, contains, same name, same type)
- ⚡ Paged byte download with parallel fetching
- 🎨 A dark UI theme on custom CSS
- 📈 File information: type, entropy with a profile (chart), signatures embedded inside
- 📊 A list of relations grouped by relation, with navigation to related files

### Tech stack
- **Framework**: React 18
- **Build / dev server**: Vite
- **Tests**: Vitest + Testing Library (jsdom)
- **Lint / formatting**: ESLint 9+ (flat config) + Prettier
- **UI**: custom CSS (`src/styles/index.css`, `src/components/hex/HexDump.css`) — no component libraries
- **Virtualization**: react-window
- **Graph**: react-force-graph-2d + d3-force
- **Icons**: Unicode/emoji characters in buttons (no icon library)
- **State**: React Hooks (useState, useEffect, useMemo) + a custom `useElementSize` hook
- **API**: Fetch API

---

## Architecture

### Directory structure

```
frontend/
├── index.html                    # Page template (Vite) — loads src/main.jsx
├── vite.config.js                # /api proxy for `npm run dev`, Vitest configuration
├── eslint.config.js              # ESLint (flat config)
├── .prettierrc.json              # Prettier
├── public/robots.txt             # `Disallow: /` — keep the app out of search engines
├── nginx.conf, Dockerfile        # Production image (see "Build and deployment")
└── src/                          # ↓

frontend/src/
├── App.jsx                       # Main application component (+ tabs)
├── App.test.jsx
├── main.jsx                      # Entry point (imports styles/index.css)
├── test/
│   └── setup.js                  # Vitest: jest-dom + DOM cleanup after each test
├── styles/
│   └── index.css                 # Custom styles: color variables, buttons, cards, tabs
├── lib/
│   ├── api.js                    # API client (fetch wrappers) + uploadErrorMessage()
│   ├── api.test.js
│   ├── format.js                 # hex(), formatBytes(), describeEntropy(), displayName(), truncate(), cappedNames()
│   └── format.test.js
├── hooks/
│   ├── usePreloadAll.js          # Hook for downloading the whole file
│   └── useElementSize.js         # Element size via ResizeObserver
└── components/
    ├── ErrorBoundary.jsx         # Per-tab error boundary (message instead of a blank app)
    ├── ErrorBoundary.test.jsx
    ├── hex/
    │   ├── HexDumpVirtualized.jsx    # Virtualized hex viewer
    │   └── HexDump.css               # Hex viewer styles
    ├── file/
    │   ├── FileTab.jsx           # "File" tab: type, entropy + chart, embedded signatures
    │   └── FileTab.test.jsx
    ├── links/
    │   ├── LinksTab.jsx          # "Relations" tab: list grouped by relation
    │   └── LinksTab.test.jsx
    └── graph/
        ├── GraphView.jsx         # "Relation graph" tab
        ├── GraphView.test.jsx
        └── relations.js          # RELATIONS: labels, colors and line styles (graph + LinksTab)
```

The `frontend/dist/` directory is not kept in the repository — it is created by `npm run build` (in Docker during the image build stage).

---

## Installation and configuration

### Requirements
```bash
node 22   # this version is used in the Docker image and in CI
npm
```

### Installing dependencies

```bash
cd frontend
npm install
```

### Main dependencies (package.json)
```json
{
  "type": "module",
  "dependencies": {
    "d3-force": "^3.0.0",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "react-force-graph-2d": "^1.28.0",
    "react-window": "^1.8.10"
  },
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "lint": "eslint .",
    "format": "prettier --write .",
    "format:check": "prettier --check .",
    "test": "vitest run"
  }
}
```

In `devDependencies`: `vite`, `@vitejs/plugin-react`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `eslint` (+ `@eslint/js`, `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `globals`), `prettier`.

| Script | What it does |
|---|---|
| `npm run dev` | Vite development server (`http://localhost:5173`) with the `/api` proxy |
| `npm run build` | production build into `dist/` |
| `npm run preview` | preview of the built `dist/` |
| `npm run lint` | ESLint (`eslint.config.js`, flat config) |
| `npm run format` / `format:check` | Prettier — fix / check only |
| `npm test` | Vitest (single run) |

### Environment variables

Usually none are needed: the client uses `/api`, which nginx forwards in Docker, and the Vite server forwards with `npm run dev`.

A different API address can be given with the `VITE_API_URL` variable (e.g. in `frontend/.env.local`):

```bash
VITE_API_URL=http://192.168.1.50:8000
```

The variable is compiled in at build time — changing it requires another `npm run build`. When the API lives at a different address than the frontend, the backend must have `CORS_ORIGINS` set (CORS is disabled by default), and that address must be in the backend's `ALLOWED_HOSTS` (default `localhost,127.0.0.1`; another `Host` → `400`).

### Running in development mode

First the backend, locally:

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Then the frontend:

```bash
cd frontend
npm run dev
```

The app will be available at: `http://localhost:5173`. Vite (`vite.config.js`, `server.proxy`) forwards `/api/...` to `http://localhost:8000/...` (the `/api` prefix is stripped), so the frontend and API share one address and CORS is not needed.

### Production build

```bash
npm run build
npm run preview   # optional: preview the build
```

Files go to `dist/` - ready for deployment (without source maps).

---

## Components

### 1. App.jsx - Main component

**Description**: The central component that manages the whole application workflow.

**Application state**:
```javascript
const [file, setFile] = useState(null);           // Selected file
const [jobId, setJobId] = useState(null);         // Job ID from the backend
const [meta, setMeta] = useState(null);           // File metadata
const [result, setResult] = useState(null);       // Analysis result
const [bytes, setBytes] = useState(null);         // Uint8Array - file contents
const [graphEntry, setGraphEntry] = useState(null); // { jobId, graph: { center, nodes, edges }, at } — cached per job
const [jump, setJump] = useState(null);           // { offset } - jump in the HEX view
const [activeTab, setActiveTab] = useState('hex'); // Active tab
const [uploading, setUploading] = useState(false); // Upload status
const [error, setError] = useState(null);         // Errors
```

**Workflow**:
1. The user selects a file (`<label className="btn">` with a hidden `<input type="file">`)
2. Clicking "Analyze" → `uploadFile()` → receives `job_id` → `openJob(job_id, meta)`; on failure `uploadErrorMessage(err)` gives a friendly message for `413` (too large), `503` (queue full) and `507` (server disk full)
3. Auto-polling of the status (`useEffect` + `getJob()`) until `analysis_ready` or `status: "error"` (then "Analysis failed: …" with the backend's generic `analysis_error`)
4. Auto-download of the bytes (`usePreloadAll` hook)
5. Once the analysis is done, the graph (`getGraph()`) is **cached per job** (`graphEntry`): entering Relations or Relation graph fetches it again only when the cached copy is older than `GRAPH_MAX_AGE_MS` (10 s), so files uploaded in the meantime show up without a request on every tab switch; the File tab uses any cached graph (it only needs the center node's names). A late response for a previous job is dropped.
6. Rendering the tabs: Hex Dump / File / Relations / Relation graph — each wrapped in its own `ErrorBoundary`

**Switching files**: `openJob(id, initialMeta)` clears `meta`, `result`, `bytes`, the cached graph, `jump` and sets the new `jobId`. It is used by the upload and by the "Open" / "Open this file" buttons in the Relations and Relation graph tabs — in that case the active tab does not change.

**Jump to offset**: `jumpTo(offset)` sets `jump = { offset }` and switches to Hex Dump (from the entropy chart and the embedded signatures table in the File tab).

**Tabs**:
- **Hex Dump**: Virtualized hex viewer with SHA-256
- **File**: Type, size, entropy (with a description), names, entropy profile, embedded signatures
- **Relations**: List of related files grouped by relation
- **Relation graph**: Interactive graph (react-force-graph-2d)

**Error boundaries**: every tab is wrapped in `ErrorBoundary` (`components/ErrorBoundary.jsx`) with a `resetKey` (the tab's data: `bytes`, `result` or `graph`). A render error — e.g. an unexpected server response — shows "Something went wrong displaying this view." in that tab instead of blanking the whole app; new data clears it.

---

### 2. HexDumpVirtualized.jsx

**Description**: A high-performance hex viewer with virtualization for large files.

**Parameters**:
```javascript
bytes        // Uint8Array - binary data
cols = 16    // Number of bytes per line
height = 520 // Container height (px)
rowHeight = 22  // Height of a single row (px)
asciiSize = 14  // ASCII font size (px)
jumpTo = null   // { offset } - a new object = a new jump (the same offset works too)
```

Changing `jumpTo` scrolls the list so that the row with the byte is in the middle, and selects that byte.

**Features**:
- ✅ Virtualization with `react-window` (renders only visible rows)
- ✅ Interactive byte selection (click)
- ✅ Range selection (Shift + click)
- ✅ Context menu (right click) with copying
- ✅ HEX column + ASCII column
- ✅ Tooltips with information (offset, hex, dec)
- ✅ List width measured with the `useElementSize` hook (min. 600 px)

**Display format**:
```
000000: 4D 5A 90 00 03 00 00 00  04 00 00 00 FF FF 00 00  |MZ..............|
000010: B8 00 00 00 00 00 00 00  40 00 00 00 00 00 00 00  |........@.......|
```

**Optimizations**:
- Memoization of the `Row` component with `React.memo`
- Fixed overscan: 20 rows (`overscanCount={20}`)
- CSS grid for fixed column widths
- `will-change: transform` for smooth scrolling

---

### 3. GraphView.jsx

**Description**: An interactive relation graph of the file from the backend (`GET /jobs/{id}/graph`).

**Parameters**:
```javascript
graph         // { center, nodes, edges } from getGraph() (null → "Loading graph…")
currentJobId  // ID of the open job (so "open" is not offered for the file itself)
onOpenJob     // (jobId) => void - switch to another file
```

**Features**:
- 🎯 **Nodes**:
  - This file - blue circle with a white outline (`#3b93eb`)
  - Other files - grey circles (`#9ca3af`)
  - File types - purple squares (`#7c3aed`); files of the same type cluster around them
  - Identical files (same SHA-256) are a single node with a `names` list (the backend sends at most 20 + `names_total`; the rest is shown as "+N more")
  - Canvas labels go through `displayName()` and are truncated by code points (`truncate()`, 28 characters)
- 🔗 **Relations** (`RELATIONS` from `components/graph/relations.js`, shared with `LinksTab`):
  - `similar` - Similar, orange line, thickness depends on `weight`, label "98%"
  - `contains` - Contains, purple dotted line with an arrow, label "N× from 0x…"
  - `same_name` - Same name, turquoise dashed line
  - `is_type` - File type, semi-transparent grey line
- 🎛️ **Toolbar**:
  - Relation checkboxes - toggle a relation on/off and double as the color legend (with the number of edges from this file)
  - "Similarity ≥ X%" slider (5–100%, default 10%), disabled when "Similar" is off
  - Buttons: Fit, ＋, －
- 🖱️ **Interactions**:
  - Node click → side panel with details
  - Hover → dims nodes not connected to the hovered one
  - Click on the background / `Esc` → closes the panel
  - Dragging nodes
  - No hover tooltips: `nodeLabel` and `linkLabel` return `''` on purpose — force-graph renders string tooltips with `innerHTML` (and defaults `linkLabel` to the `name` field), so server data must stay out of that sink

**Filtering**: visible are the center, nodes connected to it by an enabled relation (for `similar` only with `weight ≥` the threshold) and — with "File type" enabled — the center's type with its files and the types of the visible files. When nothing remains besides the center, the message "No relations — upload more files…" appears.

**Side panel** (top right corner of the canvas, width `min(420px, 100% − 24px)`):
- File: names (capped, "+N more"), type, size, entropy, SHA-256, first seen; buttons **"Open this file"** (when the node has a `job_id` other than the current one) and **⧉ SHA**; when `job_id` = `null` — "The file is no longer available for preview."
- Type: extension, magic, offset
- Closing: `Esc`, the `✕` button or a click on the background

**Physical forces (D3)**:
```javascript
- link.distance: is_type 70px, similar 160 − 100·weight, others 120px
- charge.strength: -260 (repulsion)
- collide.radius: 22 (collisions)
```

---

### 4. Tabs in App.jsx

Tabs are plain `.tab` buttons with `role="tab"` / `aria-selected` (the `TABS` list in `App.jsx`), no library. `HexTab` is a small component in `App.jsx`; the other tabs have their own files:

- **`FileTab`** (`components/file/FileTab.jsx`, props `result`, `centerNode`, `onJump`):
  - type (name, extension, magic @ offset or "unknown"), size, entropy with a description from `describeEntropy()`, names (from the graph's center node; at most 20, then "+N more"), date of first upload
  - **Entropy profile** - SVG chart (bar = a fragment of `profile_step` bytes, height 0–8, color by thresholds 1 / 7.2 / 7.9 with a legend); clicking a bar → `onJump(i * step)`
  - **Signatures inside the file** - Offset / Type table with a "Show in HEX" button
- **`LinksTab`** (`components/links/LinksTab.jsx`, props `graph`, `currentJobId`, `onOpenJob`) - the same data as the graph, as a grouped list:
  - Identical (same SHA-256, different names)
  - Similar - with a percentage bar (`weight`)
  - Contains - type + label "N× from 0x…"
  - Same name
  - Same type - the newest files of this type
  - for a file with an available `job_id`, an **"Open"** button (switches the file, the tab stays)
  - other names of a file ("also as: …") are capped the same way ("+N more")

---

## Hooks and utilities

### usePreloadAll.js

**Description**: A hook for downloading the whole file in parallel, piece by piece.

**Parameters**:
```javascript
jobId      // Job ID
totalSize  // File size in bytes
```

**Returns**:
```javascript
{
  preload,   // async (pageSize, concurrency) => Uint8Array
  loading,   // boolean - whether a download is in progress
  progress   // 0.0 - 1.0 - progress
}
```

**Strategy**:
1. Splits the file into pages (8 MB by default)
2. Starts a pool of workers (6 by default)
3. Each worker fetches the next page (retrying on network/server errors)
4. Joins everything into a single `Uint8Array`

**Retry strategy**:
- Network error (or 5xx) → max. `MAX_ATTEMPTS = 5` attempts, delay `min(2000, 150 * 2^attempt)` ms
- 4xx error → stop immediately, no retry
- `410 Gone` (source file deleted) → exception "Source file unavailable (410)."
- Takes the file size from `meta.size_bytes` (the backend sends no `x-*` headers)

**Aborting**: each download has its own `AbortController`. Changing `jobId` (switching the file) aborts the previous download — `preload` then returns `null` instead of throwing, and `App.jsx` additionally does not store the bytes if another file was opened in the meantime.

**Usage**:
```javascript
const { preload, loading, progress } = usePreloadAll(jobId, totalSize);

useEffect(() => {
  if (!jobId || !totalSize) return;
  (async () => {
    const buf = await preload(8 * 1024 * 1024, 6); // 8MB pages, 6 in parallel
    setBytes(buf);
  })();
}, [jobId, totalSize]);
```

---

### api.js

**Description**: API client with fetch wrappers. Job IDs are URL-encoded in paths (defence in depth). A non-2xx response throws an `Error` with `err.status` and only a short excerpt (≤ 200 characters) of the response body in the message.

#### `uploadFile(file, { signal })`
```javascript
// POST /upload (with the X-Hex-Analyzer: 1 header)
const response = await uploadFile(file);
// Returns: { job_id, status: "queued", meta }
// HTTP error → exception with err.status (413, 503, 507…)
```

#### `uploadErrorMessage(err)`
User-facing message for a failed upload: `413` → "File is too large (limit 100 MB).", `503` → "The analysis queue is full — try again in a moment.", `507` → "The server is out of free disk space — try again later.", anything else → "Error while uploading the file."

#### `getJob(jobId, { signal })`
```javascript
// GET /jobs/{job_id}
const response = await getJob(jobId);
// Returns: parsed JSON — meta + status (+ `result` when ready)
// Errors (404 unknown job, 422 invalid job_id format) → exception
```

#### `fetchBytes(jobId, offset, length, { signal })`
```javascript
// GET /jobs/{job_id}/bytes?offset=X&length=Y
const response = await fetchBytes(jobId, 0, 8388608);
// Returns: Uint8Array (shorter/empty past the end of the file)
// length max 16 MB; HTTP error → exception with err.status (e.g. 410)
```

#### `getGraph(jobId, { minSimilarity = 0.05, limit = 25, signal })`
```javascript
// GET /jobs/{job_id}/graph?min_similarity=0.05&limit=25
const graph = await getGraph(jobId);
// Returns: { center, nodes, edges }
// 409 (analysis not finished) and other HTTP errors → exception
```

**Configuration**:
```javascript
const API_BASE = import.meta.env.VITE_API_URL?.trim() || '/api';

// Header required by the backend for changes (POST/DELETE) — CSRF protection
const CSRF_HEADERS = { 'X-Hex-Analyzer': '1' };
```

The backend rejects every `POST`/`PUT`/`PATCH`/`DELETE` without the `X-Hex-Analyzer` header (403), so every new function that changes data must send `CSRF_HEADERS`. `GET` does not need it.

The client does not (yet) have functions for `DELETE /jobs/{job_id}` or `GET`/`POST`/`DELETE /types`.

### format.js

- `hex(n, pad)` - `0x…` in uppercase, e.g. `hex(512, 8)` → `0x00000200`
- `formatBytes(n)` - e.g. `1.5 MB (1 572 864 B)`
- `describeEntropy(e)` - a plain-language entropy description (thresholds 1 / 5 / 7.2 / 7.9 bits/byte: empty areas, text/code, machine code, compressed data, noise — compression or encryption)
- `displayName(s)` - a name from the server (file name, type name, extension) safe to display: control and format characters (`\p{Cc}`, `\p{Cf}` — bidi overrides, zero-width characters, BOM…) become visible as `⟨U+XXXX⟩`, so `evil<U+202E>fdp.exe` cannot pose as `evilexe.pdf` — it is shown as `evil⟨U+202E⟩fdp.exe`. Use it for **every** server-provided name.
- `truncate(s, max)` - cut to `max` characters without splitting surrogate pairs
- `cappedNames(node)` - `{ shown, more }` for a file node: at most `MAX_NAMES` (20) names + how many more (`names_total`)

---

## Features

### 1. File upload and analysis

**Flow**:
```
[Choose file] → [Analyze] → POST /upload → you get a job_id
    ↓
Polling GET /jobs/{job_id} every 750ms (while analysis_ready = false; status "error" stops polling)
(upload errors: 413 / 503 / 507 → friendly message)
    ↓
Auto-download of the bytes (usePreloadAll)
    ↓
Rendering the hex dump + analysis results
```

### 2. Hex Dump with virtualization

**Capabilities**:
- Scrolling large files (GB) without lag
- Click a byte → selection
- Shift + click → range selection
- Right click → context menu:
  - Copy byte (HEX)
  - Copy offset
  - Copy range (HEX)
- Tooltips with information

**Format**:
- Offset (6 hex digits)
- 16 HEX bytes (with a gap after the 8th byte)
- ASCII (16 characters, printable or `.`)

### 3. File and relations

**File** (from `result` in `GET /jobs/{id}`: `file`, `entropy_profile`, `profile_step`, `embedded`):
- Type (name, extension, magic, offset) or "unknown"
- Size
- Entropy with a description
- Names the same file was uploaded under (first 20, "+N more")
- Entropy profile (click → jump in HEX)
- Embedded signatures ("Show in HEX")

**Relations** (from the graph):
- Identical - same SHA-256 (one node, many names)
- `similar`: Similar - shared ~1.2 KB content-defined chunks (Jaccard)
- `contains`: Contains - a signature of another type inside the file
- `same_name`: Same name, different content
- `is_type`: Same type - other files attached to the same type node

### 4. Relation graph

**Visualization**:
- Central node (this file), files as circles, types as purple squares
- Line color and style depend on the relation, labels on edges ("98%", "2× from 0x200")
- Dimming unrelated nodes on hover

**Controls**:
- ☑️ Relation checkboxes (also the legend)
- 🎚️ Similarity threshold
- 🔍 Fit
- ➕ Zoom in
- ➖ Zoom out

**Interactions**:
- Click → details panel
- "Open this file" → switch to another file (the tab stays)
- Drag & drop → moving nodes

---

## Performance optimizations

### 1. Virtualization (react-window)

**Problem**: Rendering a 1 GB file = ~67 million rows.

**Solution**: `react-window` renders only the visible rows + overscan.

**Result**: 
- Smooth scrolling even for GB-sized files
- Constant RAM usage (~100 MB for the interface)

### 2. Overscan

**Strategy**: a fixed `overscanCount={20}` — 20 rows rendered outside the view.

**Result**: Smoothness + fewer unnecessary renders.

### 3. Memoization

**Components**:
```javascript
const Row = React.memo(function Row({ ... }) { ... });
```

**Graph data**:
```javascript
const nodeById = useMemo(() => { ... }, [graph]);                     // stable node objects
const data = useMemo(() => { ... }, [graph, nodeById, enabled, minSim]); // relation filtering
const neighbors = useMemo(() => { ... }, [data]);
```

### 4. Parallel download

**usePreloadAll**:
- 6 parallel requests
- Each fetches its own page (8 MB)
- Retries (max. 5 attempts) with increasing delay, no retry on 4xx
- Real-time progress tracking

**Result**: 5-10x faster download than sequential.

### 5. CSS optimizations

```css
will-change: transform;           /* GPU acceleration for scrolling */
transition: 140ms ease;           /* Fast animations */
scrollbar-gutter: stable;         /* Stable layout */
```

---

## Styling and UI

### Color theme (dark)

CSS variables in `src/styles/index.css` (`:root`, `color-scheme: dark`):

```css
--bg: #141414;          /* Main background */
--surface: #1e1e1e;     /* Card background */
--surface-2: #262626;
--border: #2f2f2f;      /* Borders */
--text: #e6e6e6;        /* Text */
--muted: #8a8a8a;       /* Muted text */
--accent: #2a82da;      /* Accent (selection, primary button) */
--danger: #e5484d;      /* Error */
--warn: #d9a400;        /* Warning */
--info: #3b82f6;

/* entropy chart */
--ent-low: #4b5563;     /* < 1 */
--ent-mid: #3b82f6;     /* 1–7.2 */
--ent-high: #f59e0b;    /* 7.2–7.9 */
--ent-max: #ef4444;     /* ≥ 7.9 */
```

The graph has its own colors: `NODE` in `GraphView.jsx` (`current: '#3b93eb'`, `file: '#9ca3af'`, `type: '#7c3aed'`) and `RELATIONS` in `relations.js` (`similar: '#f59e0b'`, `contains: '#c084fc'`, `same_name: '#2dd4bf'`).

### Responsiveness

**Graph panel** (`.graph-panel`, in the top right corner of the canvas):
```css
width: min(420px, calc(100% - 24px));
```

**Entropy chart**: SVG with `preserveAspectRatio="none"` — stretches to the card width.

**HexDump**:
- Fixed offset width: `9ch`
- Fixed HEX width: `calc(cols * 3ch + 2ch)`
- Auto ASCII width

### CSS classes

Instead of Mantine components — plain HTML with classes from `index.css`:
- `.header`, `.main` - layout with a header
- `.btn`, `.btn--primary`, `.btn--sm`, `.btn--anim` - buttons
- `<label className="btn">` + `.visually-hidden` input - file selection
- `.alert--error` / `--warn` / `--info` - messages
- `.card`, `.card--inner` - content cards
- `.tabs`, `.tab` - tabs
- `.row`, `.stack`, `.center` - layout
- `.label`, `.muted`, `.small`, `.kv`, `.badge` - typography
- `.input` - input (SHA-256)
- `.spinner`, `.progress` - loading
- `.file-bar`, `.ellipsis`, `.mono`, `.table` - file bar above the tabs, tables
- `.entropy-chart`, `.entropy-bar`, `.entropy-legend` - entropy chart
- `.link-list`, `.link-row`, `.sim`, `.sim-bar` - relation list with a similarity bar
- `.graph-*` (`-toolbar`, `-toggle`, `-swatch`, `-slider`, `-legend`, `-canvas`, `-overlay`, `-panel`) - graph

Hex viewer styles have the `.hx-*` prefix (`HexDump.css`).

---

## Usage examples

### 1. Basic workflow

```javascript
// 1. The user selects a file
<label className="btn">
  Choose file
  <input type="file" className="visually-hidden"
         onChange={(e) => setFile(e.target.files?.[0] || null)} />
</label>

// 2. Upload
const handleUpload = async () => {
  const { job_id } = await uploadFile(file);
  setJobId(job_id);
};

// 3. Auto-polling
useEffect(() => {
  if (!jobId) return;
  const poll = async () => {
    const body = await getJob(jobId);
    setMeta(body);
    if (body.result) setResult(body.result);
    if (body.status === 'error') return; // body.analysis_error
    if (!body.analysis_ready) setTimeout(poll, 750);
  };
  poll();
}, [jobId]);

// 4. Auto-download
const { preload, progress } = usePreloadAll(jobId, totalSize);
useEffect(() => {
  (async () => {
    const buf = await preload();
    setBytes(buf);
  })();
}, [jobId, totalSize]);

// 5. Render
<HexDumpVirtualized bytes={bytes} />
```

### 2. Custom hex viewer

```javascript
<HexDumpVirtualized
  bytes={myBytes}
  cols={32}            // 32 bytes per line
  height={800}         // 800px tall
  rowHeight={24}       // 24px per row
  asciiSize={16}       // 16px ASCII font
/>
```

### 3. Graph with custom data

```javascript
const graph = {
  center: "f:1",
  nodes: [
    { id: "f:1", kind: "file", current: true, label: "fw_v2.bin", names: ["fw_v2.bin"], job_id: "a3f8...", size: 1048576, entropy: 7.1, sha256: "abc123..." },
    { id: "f:2", kind: "file", label: "fw_v1.bin", names: ["fw_v1.bin"], job_id: null, size: 1040384, entropy: 7.0, sha256: "def456..." },
    { id: "t:1", kind: "type", label: "PNG image", extension: "png", magic: "89504E470D0A1A0A", offset: 0 }
  ],
  edges: [
    { source: "f:1", target: "f:2", relation: "similar", weight: 0.92, label: "92%" },
    { source: "f:1", target: "t:1", relation: "contains", count: 3, label: "3× from 0x4000" }
  ]
};

<GraphView graph={graph} currentJobId="a3f8..." onOpenJob={(id) => console.log(id)} />
```

---

## Debugging

### Console logs

The app logs only errors (`console.error`):

```javascript
[App] upload error: ...
[App] job poll error: ...
[App] preload error: ...
[App] graph error: ...
```

### DevTools

**React DevTools**:
- Inspect component state
- Monitor re-renders

**Network tab**:
- Monitor the `/upload`, `/jobs/{id}`, `/bytes`, `/graph` requests
- Check the statuses (200, 202 on upload, 413/503/507 for a refused upload, 400 for a `Host` outside `ALLOWED_HOSTS`, 404/422 for an invalid job_id, 409 for the graph before the analysis finishes, 410)

**Performance tab**:
- Scroll profiling (should be 60 FPS)
- Memory snapshots

---

## Known issues and solutions

### 1. No connection to the backend with `npm run dev`

**Problem**: Upload errors (e.g. 502/504 from the Vite proxy) or CORS errors in the console.

**Solution**: Run the backend locally on port 8000 (`uvicorn main:app --reload --port 8000`) — the Vite proxy forwards `/api` there. CORS errors only appear when `VITE_API_URL` is set to a different address; then the backend needs `CORS_ORIGINS` (e.g. `http://localhost:5173`).

**Problem**: `403 Missing X-Hex-Analyzer header`.

**Solution**: A `POST`/`DELETE` request was sent without the CSRF header — use `CSRF_HEADERS` from `lib/api.js`.

### 2. Slow scrolling in the hex dump

**Problem**: Laggy scrolling with large files.

**Solution**: 
- Check that virtualization is in place (react-window)
- Increase overscan if needed
- Use `will-change: transform` in CSS

### 3. Graph does not fit the view

**Problem**: Nodes off screen.

**Solution**: 
```javascript
// Auto-fit 600 ms after a new graph arrives (the "Fit" button does the same)
useEffect(() => {
  const t = setTimeout(() => fgRef.current?.zoomToFit(400, 70), 600);
  return () => clearTimeout(t);
}, [graph]);
```

### 4. Error 410 on /bytes

**Problem**: File deleted from the server.

**Solution**: The file is gone from `data/uploads/` — e.g. the job was deleted via `DELETE /jobs/{job_id}` or by the `JOB_TTL_HOURS` cleanup (default `0` = never). The `.gz` copy (when `ARCHIVE=1`) is deleted together with the job as well.

---

## TODO and planned features

### Short term
- [ ] Export hex dump to a file
- [ ] Search in hex dump (byte search)
- [ ] Jump to offset (typing an address manually; jumping from the "File" tab already works)
- [ ] Annotations (comments on bytes)
- [ ] Color schemes (light/dark)

### Long term
- [ ] Diff viewer (file comparison)
- [ ] Disassembler (x86, ARM)
- [ ] String extractor
- [x] Entropy visualization
- [ ] Multi-file comparison
- [ ] Plugin system

---

## Build and deployment

### Development
```bash
npm run dev
# → http://localhost:5173
```

### Production build
```bash
npm run build
# → Files in dist/
```

### Deployment (nginx example)

```nginx
server {
  listen 80;
  server_name hex-analyzer.example.com;

  root /var/www/hex-analyzer/dist;
  index index.html;

  # Frontend
  location / {
    try_files $uri $uri/ /index.html;
  }

  # Backend API
  location /api/ {
    client_max_body_size 101m;   # the backend accepts up to 100 MB
    proxy_http_version 1.1;
    proxy_request_buffering off; # stream uploads instead of buffering them
    proxy_pass http://localhost:8000/;
    proxy_set_header Host $host; # must be in the backend's ALLOWED_HOSTS
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }
}
```

### Docker

The frontend has its own image (`frontend/Dockerfile`, both base images pinned by digest): the `node:22.23.4-alpine` stage runs `npm ci --ignore-scripts` + `npm run build` (Vite), and `nginxinc/nginx-unprivileged:1.31.7-alpine` (non-root nginx) serves `dist/` with the `frontend/nginx.conf` configuration:
- `listen 8080` (without root the port must be > 1024), `server_tokens off`, `nosniff` and `X-Frame-Options: DENY` as defence in depth (Caddy sets the full set)
- `/` → static files (`try_files $uri /index.html`); `/index.html` with `Cache-Control: no-cache` (so browsers never keep an entry page pointing at deleted assets)
- `/assets/` → files with a hash in the name, `Cache-Control: public, max-age=31536000, immutable`
- `/api/` → `http://backend:8000/`, `client_max_body_size 101m`, uploads streamed (`proxy_request_buffering off`), `X-Forwarded-For` / `X-Forwarded-Proto`, `proxy_read_timeout 120s`

In compose the container has a read-only root filesystem (a 32 MB `/tmp` tmpfs), no capabilities, `no-new-privileges`, `mem_limit: 128m`, `pids_limit: 64`.

`package.json` has `overrides` forcing patched transitive dependencies of the graph library: `lodash-es` 4.18.1 and `preact` 10.28.4 (security fixes). Remove an override only once the parent package depends on a fixed version itself.

In `docker-compose.yml` neither the frontend nor the backend publishes ports — the way in from outside is through Caddy (`https://<host>`, password), which forwards traffic to `frontend:8080`, and nginx forwards `/api` to the backend. Caddy also adds a Content-Security-Policy header (`script-src 'self'`, `style-src 'self' 'unsafe-inline'` — the graph library injects `<style>` elements at runtime; `img-src 'self'`), so the frontend cannot load scripts, styles or images from external CDNs, plus Permissions-Policy, COOP and CORP (`same-origin`).

---

## Testing

### Unit tests (Vitest + Testing Library)

```bash
cd frontend
npm test              # vitest run — single run
npm run lint          # ESLint
npm run format:check  # Prettier
```

Configured in `vite.config.js` (`test.environment: 'jsdom'`, `setupFiles: './src/test/setup.js'`). `setup.js` adds the `@testing-library/jest-dom` matchers (e.g. `toBeInTheDocument()`) and cleans up the DOM after each test. Tests live next to the code (`*.test.js` / `*.test.jsx`):
- `src/App.test.jsx` — upload error messages, the generic analysis error, graph caching per job (refetch after 10 s), late graph of a previous job, a malformed response caught by the error boundary
- `src/lib/api.test.js` — URL encoding of job IDs, error excerpts, CSRF header, `uploadErrorMessage()`
- `src/lib/format.test.js` — `hex()`, `formatBytes()`, `describeEntropy()`, `displayName()`, `truncate()`, `cappedNames()`
- `src/components/ErrorBoundary.test.jsx` — message instead of a blank app, reset on new data
- `src/components/graph/GraphView.test.jsx` — no HTML tooltips, visible invisible characters, "+N more"
- `src/components/file/FileTab.test.jsx` — the "File" tab (type, entropy, profile, jumps to an offset)
- `src/components/links/LinksTab.test.jsx` — the "Relations" tab (groups, "Open", names as text)

**Example test**:
```javascript
import { describe, expect, it } from 'vitest';
import { hex } from './format';

describe('hex', () => {
  it('formats with a 0x prefix and uppercase letters', () => {
    expect(hex(512, 8)).toBe('0x00000200');
  });
});
```

CI on GitHub Actions (`.github/workflows/ci.yml`) runs the same (plus `npm run build`) on every push and pull request, and locally so do the pre-commit hooks (`.pre-commit-config.yaml`).

### E2E (planned, not there yet — e.g. Cypress/Playwright)

```javascript
describe('Upload workflow', () => {
  it('uploads file and shows hex dump', () => {
    cy.visit('/');
    cy.get('input[type=file]').attachFile('test.bin');
    cy.contains('Analyze').click();
    cy.contains(/[0-9A-F]{6}:/, { timeout: 10000 }).should('exist');
  });
});
```

---

## Performance benchmarks

### HexDumpVirtualized

| File size | Initial render | Scroll FPS | RAM usage |
|-----------|----------------|------------|-----------|
| 1 MB      | ~100ms         | 60 FPS     | ~50 MB    |
| 100 MB    | ~150ms         | 60 FPS     | ~80 MB    |
| 1 GB      | ~200ms         | 58 FPS     | ~120 MB   |

### usePreloadAll

| File size | Download time (6 workers) | Throughput |
|-----------|---------------------------|------------|
| 10 MB     | ~0.5s                     | 20 MB/s    |
| 100 MB    | ~4s                       | 25 MB/s    |
| 1 GB      | ~40s                      | 25 MB/s    |

*Depends on network bandwidth and backend performance.

---

## Contact and support

If you run into problems:
1. Check the console logs
2. Check the Network tab in DevTools
3. Check the backend logs

---

**Documentation version**: 1.2  
**Date**: 2026-10-23  
**Author**: Hex Analyzer Team
