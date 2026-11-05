# R4 C (Photos and connectors): what the integrator registers

Everything is OFF until connected. No shared wiring file was edited.

## Tools (permission row `connectors`; all pass the gateway)
`from jarvis.photos.tools import ConnectorDeps, tools` then `for t in tools(ConnectorDeps(github=..., youtube=..., photos=...)): reg.register(t)`.
A dep that is `None` registers no tools. Names: `connect_github`, `connect_youtube`, `github_profile`,
`github_repos`, `github_activity` (READ_ONLY), `photos_import` (REVERSIBLE), and `youtube_own_channel` (READ_ONLY; it
lives under the EXISTING slice-12 `youtube_*` permission row, not `connectors`). No tool takes a token.
Not given to a training brain (they read private accounts).

Build the deps:
- `GithubClient(GithubStore(docs, keyring, prefix=s.firestore_prefix))` (needs a `Keyring`; None => github=None)
- `YouTubeOwn(google_connector, media.ledger)` (needs the Google link AND the slice-12 `QuotaLedger`
  that `media.service` builds; else None). Every owner-token call is counted in `YOUTUBE_UNITS`
  (1 unit for the channel, 2 for channel + uploads) and a Google "quota gone" answer closes the day.
  Decision (py-M5): the ledger is wired, not the methods deleted.
- `PhotosService(PickerClient(google_connector), BridgeHomeEdge(home_client), faces_service, ContactsClient(google_connector), PhotosState(docs, prefix=s.firestore_prefix))`
  only when `s.photos_enabled`, the Google link, the `FacesService` and the R3 `HomeClient` exist; else photos=None.

## Routes
`from jarvis.photos.api import install_connectors; install_connectors(app)` (like `install_faces`),
then set `app.state.connectors = ConnectorDeps(...)`. Routes under `/v1/connectors`:
GET status, PUT/DELETE `/github` (token body, never echoed or logged), POST `/photos/start`,
`/photos/import`, `/photos/enrol` (consent 422s). Owner-only, CSRF header, 20 changes/min.

## Console
`src/jarvis/api/static/console-connectors.js` (the brief said `web/`; the repo serves consoles from
`api/static/`, so it lives there). Needs a `#p-connectors` panel shell with a `.pbody` in
`console.html`, a `<script src="/static/console-connectors.js">` tag and a Deck entry `connectors`.

## Needed seams outside my scope
1. Google scope: add to `integrations/google.py` `GRANTS["photos"] = PHOTOS_SCOPE`
   (`jarvis.photos.models.PHOTOS_SCOPE` = `.../auth/photospicker.mediaitems.readonly`), with
   `GRANT_ACCEPTS["photos"] = frozenset({PHOTOS_SCOPE})`, so the owner can press Grant. `PickerClient`
   checks the stored scopes directly, so no other change is needed. `youtube.readonly` already exists.
2. Home bridge routes: add `("POST", "/bridge/v1/faces/photos")` and `("POST", "/bridge/v1/faces/enrol")`
   to `home.ports.BRIDGE_ROUTES` and implement them in the home kit.
   **Per-route request cap (D-C3), NOT a global raise of `home.client.MAX_REQUEST_BYTES`.** Replace
   the single constant with a dict keyed by `(method, path)`:
   ```python
   MAX_REQUEST_BYTES_DEFAULT = 32 * 1024
   MAX_REQUEST_BYTES: dict[tuple[str, str], int] = {
       ("POST", "/bridge/v1/faces/photos"): 6 * 1024 * 1024,  # one base64 JPEG (<= 4 MB raw)
   }
   limit = MAX_REQUEST_BYTES.get((method, path), MAX_REQUEST_BYTES_DEFAULT)
   ```
   Every other route keeps 32 KB. (6 MB covers the 4,000,000-byte picture cap after base64.)
   Reply to `/faces/photos`: `{"faces": [{"cluster": "c_<8-16 hex>", "person": "fp_<12 hex>"|null, "score": 0..1}]}`
   to `/faces/enrol`: `{}`. The cloud validates the `/faces/photos` reply STRICTLY (`EdgeReply`:
   no extra keys, <= 20 faces, `score` a real number 0..1, `person` null or `fp_`): any deviation is
   `EdgeBadReply` ("answer couldn't be understood"), distinct from "laptop isn't reachable".
   The kit holds the cluster -> embedding map; the cloud never sees embeddings. Until the routes
   exist HomeClient refuses the call and photos report "laptop not reachable" (fails closed).
   **Edge decoder checklist (before `/faces/photos` goes live).** The cloud strips EXIF/GPS/XMP/ICC
   and COM segments and rejects anything that is not a well-formed baseline/progressive JPEG with
   width/height <= 2048 (`photos.imaging`, pure bytes, no Pillow). It is a structural check, NOT a
   decoder, so decompression-bomb protection belongs to the only decoder, at home. The kit MUST:
   - set `PIL.Image.MAX_IMAGE_PIXELS` (e.g. 4,200,000 = 2048x2048) and treat
     `DecompressionBombWarning` as an error;
   - accept JPEG only (`Image.open(..., formats=["JPEG"])`) and re-check dimensions <= 2048;
   - cap the decoded body at the route's 6 MB, and process one picture per request.
3. Brain-off / no-AI: nothing here calls a model.

## Data (Docs port, `jarvis_` prefix)
`jarvis_connectors_github/{uid}` (sealed with keyring purpose `connectors`, AAD `github/{uid}/v1`),
`jarvis_photos/{uid}` ({session_id, clusters}: ids only).

## Persona lines to add (optional)
"Connect GitHub: tell the owner to paste the token in the Connectors panel, never in chat. Photos:
pick-only; unrecognised faces stay unnamed; adding a face is a panel action with consent."

## Tick jobs / brief section
None.

## Lifespan and erasure hooks
- **Close the GitHub client on shutdown:** `await github_client.aclose()` in the app lifespan (the
  client owns one `httpx.AsyncClient`).
- **Purge hook (privacy/erasure):** `PhotosService.purge(uid)` ends the live Google Picker session and
  deletes `jarvis_photos/{uid}` (every unnamed cluster id and pending enrolment). Register it in the
  Privacy panel's erasure registry next to Faces "Delete all"; also call it when the Faces registry
  is emptied for the owner. The GitHub token is removed by `GithubClient.disconnect(uid)`.
- **Photo flow behaviour the integrator should know:** one owner runs one `begin/collect/enrol` at a
  time (per-uid lock); `collect` handles one photo at a time (download -> strip metadata -> home ->
  drop) inside a 120 s budget (`timed_out` keeps the session); `begin` deletes the previous Google
  session; a locally expired or Google-404 session is cleared; an enrol while the laptop is off keeps
  the cluster *pending* so pressing Add again only re-sends to the edge (no second registry entry).
- **Token refresh on the picture download:** the download reuses `GoogleConnector._load/_refresh`
  (private) so a 401 refreshes once; if `google.py` gains a public streaming/forced-refresh method,
  switch `PickerClient._renew` to it.
- **Validation errors:** `install_connectors` registers a `RequestValidationError` handler that
  answers `/v1/connectors/*` with `{"error": "invalid_request", "detail": <known field names>}`
  only (never the submitted value) and delegates every other route to the previous handler. Install
  it AFTER any app-wide handler you add.
