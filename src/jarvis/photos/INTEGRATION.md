# R4 C (Photos and connectors): what the integrator registers

Everything is OFF until connected. No shared wiring file was edited.

## Tools (permission row `connectors`; all pass the gateway)
`from jarvis.photos.tools import ConnectorDeps, tools` then `for t in tools(ConnectorDeps(github=..., youtube=..., photos=...)): reg.register(t)`.
A dep that is `None` registers no tools. Names: `connect_github`, `connect_youtube`, `github_profile`,
`github_repos`, `github_activity` (READ_ONLY), `photos_import` (REVERSIBLE). No tool takes a token.
Not given to a training brain (they read private accounts).

Build the deps:
- `GithubClient(GithubStore(docs, keyring, prefix=s.firestore_prefix))` (needs a `Keyring`; None => github=None)
- `YouTubeOwn(google_connector)` (needs the Google link; else None)
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
   to `home.ports.BRIDGE_ROUTES`, raise `home.client.MAX_REQUEST_BYTES` to fit one base64 JPEG
   (<= ~4 MB; the picker download is size-bounded), and implement them in the home kit. Reply to
   `/faces/photos`: `{"faces": [{"cluster": "c_<8-16 hex>", "person": "fp_<12 hex>"|null, "score": 0..1}]}`;
   to `/faces/enrol`: `{}`. The kit holds the cluster -> embedding map; the cloud never sees embeddings.
   Until then HomeClient refuses the call and photos report "laptop not reachable" (fails closed).
3. Brain-off / no-AI: nothing here calls a model.

## Data (Docs port, `jarvis_` prefix)
`jarvis_connectors_github/{uid}` (sealed with keyring purpose `connectors`, AAD `github/{uid}/v1`),
`jarvis_photos/{uid}` ({session_id, clusters}: ids only).

## Persona lines to add (optional)
"Connect GitHub: tell the owner to paste the token in the Connectors panel, never in chat. Photos:
pick-only; unrecognised faces stay unnamed; adding a face is a panel action with consent."

## Tick jobs / brief section
None.
