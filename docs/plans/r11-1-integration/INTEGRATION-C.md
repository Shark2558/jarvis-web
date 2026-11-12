Version v11.1.2 · 12 Nov 2026, 09:43 IST · Release R11.1 · Status: Current · Owner: 🛠 Mark XV

# R11.1 Part C — Photos, faces and the home kit: integration note

For I1 (the integrator), the reviewers and the owner. Branch `r11-1-c`, from `r11-1-i0` (9250be1).
Plan: `docs/plans/r11-1-observations.md` (O5, O6, O7; D0, D13, D14, D15, D21-C). Brief:
`docs/plans/r11-1-integration/BRIEF-COMMON.md`.

The line this part holds everywhere: **no picture, face crop or embedding ever leaves the laptop or
appears in a cloud request, log or document; the cloud sees ids and counts only.** One exception is
R4's design and is unchanged: a photo you picked in Google Photos passes through the cloud's memory
on its way from Google to your own laptop (metadata stripped, never stored). The needle test pins
that this is the only request that carries a picture.

## 1. What was built

| | State | What | Proof (tests) |
|---|---|---|---|
| **O5** deploy script and message | built | `deploy/cloudrun.sh` enables `photospicker.googleapis.com` in its optional block; a failure warns and goes on. The Photos path says "Google Photos Picker is not switched on for your JARVIS project yet: re-run deploy/cloudrun.sh." Every other Google service keeps its own sentence. | `test_deploy_config.py::test_the_photos_picker_api_is_switched_on_and_a_failure_only_warns`, `test_r11_1_c_photos_off.py` (2), eval `o5_deploy_script_switches_photos_on`; shellcheck clean |
| **O6** 2,000 photos in the background | built | `photos_max_picked` (2,000) replaces the constant 20. An import is a job in `photo_imports/{uid}` (session id, counts, the ids still to do; never a link or a picture). Each step reads at most `photos_import_batch` (10): the laptop is asked first, the page of Google's list is read again (links expire, none is kept), each photo is downloaded, stripped of metadata by the unchanged Picker client, sent to the laptop and dropped. Steps come from the helpers' clock (`photos_import`), from the chat tool `photos_import`, and from the open Connectors panel. Line: "312 of 2,000 read · 41 faces found · paused: laptop not reachable". | `test_r11_1_c_import.py` (17), `test_r11_1_c_part.py` (jobs), `test_photos_picker.py`, `test_photos_service.py`, evals `o6_*` (5) |
| **O7** bridge routes | built | `POST /bridge/v1/faces/photos`, `POST /bridge/v1/faces/enrol`, `GET /bridge/v1/faces/groups` and (added, see 6) `POST /bridge/v1/faces/groups/forget`. Ids, counts and a confidence only. One photo a request, 6 MB on that route alone, read only after the caller's header could be this home's, one upload at a time. | `test_r11_1_c_bridge_groups.py` (19), `test_r11_1_c_bridge_wire.py` (7), `test_r11_1_c_edge.py` (8) |
| **O7** face engine | built, not run on a real face | OpenCV 5.0 YuNet (detector) and SFace (recogniser) inside the bridge, loaded only if each file's SHA-256 is the pinned one. JPEG only; the size is read from the header before decoding; a cloud photo is at most 2048 px a side and 4.2 MP; your own larger files are decoded smaller. | `test_r11_1_c_face_engine.py` (14; one loads the REAL models when `JARVIS_FACE_MODELS_DIR` is set and finds a face drawn in code) |
| **O7** watched folder | built | `PHOTOS_DIR` in `bridge.env`, off until set, mounted read-only at `/photos`. `.jpg` / `.jpeg` only, 1 KB to 40 MB, 8 folders deep, no links followed, a few a minute (6; 1 to 30). Nothing in the folder is ever written, moved or deleted. | `test_r11_1_c_bridge_folder.py` (10), `test_r11_1_c_kit.py` (14) |
| **O7** grouping | built | Unknown faces are grouped on the laptop (SQLite in the bridge's private data folder, `secure_delete` on); 3 or more pictures make a group; the same picture counts once. | `test_r11_1_c_face_store.py` (16), eval `o7_three_pictures_make_a_group` |
| **O7** naming with consent | built | Faces panel, "Unnamed groups": Name runs `PhotosService.enrol` -> `FacesService.add` (the consent check) once per person; a child needs a parent's or guardian's yes; without a yes nothing is created and the bridge is never told. The bridge has its own door too: it names a group only for a person id on the consent list it was sent. Another group of someone already added asks for nothing again. Afterwards a new photo and a camera sighting are recognised with no further step (the bridge copies the group's best crops into Frigate's library under the person's id). | `test_r11_1_c_groups.py` (14), `test_r11_1_c_api.py` (11), evals `o7_consent_check_once_per_person`, `o7_a_child_needs_a_guardians_yes`, `o7_without_a_yes_nothing_is_enrolled`, `o7_recognised_afterwards_with_no_further_step` |
| **O7** expiry, forget, Privacy row (D21-C) | built | Unnamed groups and stray faces go after `FACE_GROUPS_KEEP_DAYS` (90; 1 to 3650) counted from when first seen; each group has Forget (console and the laptop's page); Privacy has "Face groups" (count; delete all) and "Photos being read". A forget or delete is reported done only when the laptop answered; while it is away the ask waits, the row says "NOT done yet", and the `face_groups_poll` job retries. | `test_r11_1_c_part.py` (17), `test_r11_1_c_groups.py`, eval `o7_groups_expire_and_forget_waits_for_the_laptop` |
| **Needle test** | built | One journey on the real signed channel and the real bridge app: everything the laptop sent, and everything the cloud stored, logged, audited, told you or showed the model, is searched for a crop, a picture and an embedding (raw and base64). | `test_r11_1_c_needles.py` (7), eval `needles_nothing_but_ids_reaches_the_cloud` |
| **Console** (D0) | built | Connectors: the import's progress line, who was recognised, Continue now / Stop import (Stop asks first). Faces: "Unnamed groups" with Name and Forget, what waits for the laptop, and the folder's state. Existing classes only; `textContent` only; 15 lines of placement CSS. | `tests/browser/test_r11_1_c_photos.py` (see 9 for its state) |
| **Laptop's own page** | built | `http://localhost:8098/faces` gains "Faces from your photos": the only place a group's crops are shown; Forget this group; Read the folder again. | `test_r11_1_c_bridge_page.py` (8) |
| **Eval** | built, `BUILT = True` | 14 cases; three controls, each failing the part on its own: consent check skipped (2 cases fail), a crop added to the reply (8), the import done in one request (5). | `evals/r11_1/photos.py` |

New in the cloud: package `jarvis.facegroups` (store, service, privacy, tools, jobs, part), routes
under `/v1/facegroups` (`api/fix_photos.py`), tools `faces_groups` and `photos_import_status` (both
read-only), clock jobs `photos_import` and `face_groups_poll`, collections `photo_imports` and
`face_groups`, alert kind `faces_to_name` ("3 new groups of faces to name, Sir. Open Faces ->
Unnamed groups."; a count, never a name). No model call anywhere in this part, so No-AI mode and
the monthly limit change nothing.

## 2. Licences read (12 Nov 2026)

Both model licences are permissive, so the plan's fallback was not needed. No AGPL or GPL
component is used.

| What | Licence | Read at | SHA-256 |
|---|---|---|---|
| YuNet face detector, `face_detection_yunet_2026may.onnx` (229,738 bytes) | MIT, (c) 2020 Shiqi Yu; the folder's README: "All files in this directory are licensed under MIT License" | `https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_detection_yunet` (`LICENSE`) | model `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0`; licence text in the kit `c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958` |
| SFace face recogniser, `face_recognition_sface_2021dec.onnx` (38,696,353 bytes) | Apache-2.0; the folder's README says the same for all its files | `https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/face_recognition_sface` (`LICENSE`) | model `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79`; licence text in the kit `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30` |
| `opencv-python-headless` 5.0.0.93 | OpenCV: Apache-2.0; the packaging: MIT. **The Linux wheel also bundles FFmpeg under LGPL-2.1**, and libvpx, libaom, libavif, OpenBLAS, libpng, OpenSSL 1.1.1k, libgfortran / libquadmath under their own licences (its `LICENSE-3RD-PARTY.txt`). No GPL or AGPL. The bridge uses only the JPEG decoder, `dnn` and `objdetect`. | the wheel's licence files, from PyPI | see the table in 3 |
| `numpy` 2.5.4 | BSD-3-Clause (with 0BSD, MIT, Zlib, CC0-1.0 parts) | the wheel's licence files, from PyPI | see the table in 3 |

The two licence texts ship in the kit (`deploy/home/models/LICENSE-yunet-MIT.txt`,
`LICENSE-sface-Apache-2.0.txt`) beside `MODELS.txt`. **For I1 to decide:** the LGPL FFmpeg inside
the OpenCV wheel is the one thing here that is not MIT / Apache / BSD. It is an unmodified,
dynamically loaded library inside a third-party wheel that is installed on the owner's own laptop,
not distributed by us; I judged that acceptable and recorded it. If it is not, the alternative
would be `onnxruntime` (MIT) with another JPEG decoder, which this part did not build or evaluate.

## 3. Needs I1

### 3.1 Dependencies and model files (I1 adds them to the lock files; this part did not)

| Name | Version | Licence | Size | SHA-256 |
|---|---|---|---|---|
| `opencv-python-headless` | 5.0.0.93 | Apache-2.0 (+ bundled LGPL-2.1 FFmpeg, see 2) | wheel about 56 to 61 MB | cp312 manylinux x86-64 / aarch64 wheels: `ed709fdf9aa0bd1f2ed8549e71d19449b03a675bb581eb292285f6861953be37`, `09a872a157c1376ab922a69bbf22f9a95bcc7b658a9d8b436a60212b02b2eeb4`, `840bd717c21e5c11cadadc022a823315ea417f961213d06b4df010e019eb16f4`, `10818d91510e05c04568ae12b5cd120779c70c01bf897b001a6221fe430df80f` |
| `numpy` | 2.5.4 | BSD-3-Clause | wheel about 16 to 17 MB | `fbde6962867ee75b48b0ee29b2b9372ec5d617799dbaf38e82dc0596f2f7738a`, `fe4d21ab149f15e4e6043dfb0de87e6e5f34ac176cde83060e9802981fca2ac2` |
| `face_detection_yunet_2026may.onnx` | opencv_zoo 48b10fa | MIT | 229,738 bytes | `ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0` |
| `face_recognition_sface_2021dec.onnx` | opencv_zoo 48b10fa | Apache-2.0 | 38,696,353 bytes | `0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79` |

Both libraries are needed **only in the bridge image** (already hash-locked in
`deploy/home/bridge-requirements.txt`, which is this part's file) and in the test environments. The
cloud never imports them. The model files are not in the repository and not in the kit zip: the
kit's setup downloads them from the pinned addresses and keeps each only if its SHA-256 matches;
the bridge checks the same hash again before loading (see 6, deviation 1).

- `pyproject.toml`, the `homebridge` extra:

  ```diff
  -homebridge = ["aiomqtt==2.5.1", "paho-mqtt==2.1.0"]
  +homebridge = ["aiomqtt==2.5.1", "paho-mqtt==2.1.0", "opencv-python-headless==5.0.0.93", "numpy==2.5.4"]
  ```

  and the exact-string assertion on that line in
  `tests/test_deploy_home.py::test_the_mqtt_packages_are_the_reviewed_versions_with_wheel_and_sdist_hashes`.
  CI must install
  both for `tests/test_r11_1_c_face_engine.py` (its engine tests `importorskip` them, so without
  them they are skipped, not failed). Add both to `requirements.licences.json`.
- `src/jarvis/home/kit.py`: the kit refuses any import outside its allow-list, so the engine loads
  the two libraries by name (`importlib.import_module`, pinned in `RUNTIME_PACKAGES` and by
  `tests/test_r11_1_c_kit.py::test_the_picture_libraries_are_hash_locked_for_the_bridge_image`).
  The tidy form:

  ```diff
   SAFE_THIRD_PARTY = frozenset(
       {
  +        "cv2",
  +        "numpy",
           "pydantic",
  ```

  after which `homebridge/face_engine.py` may use plain lazy imports. Either way works today.

### 3.2 Tests outside this part that pin what the plan changes on purpose

These seven fail on this branch until I1 updates them. Nothing else in the neighbouring suites
fails (see 9 for what was run; the whole suite is I1's to run).

```diff
 # tests/test_r3_seams.py::test_bridge_routes_are_the_fixed_list
             ("POST", "/bridge/v1/faces/photos"),
             ("POST", "/bridge/v1/faces/enrol"),
+            # R11.1 C (D15, D21-C): the unnamed groups, and forgetting them
+            ("GET", "/bridge/v1/faces/groups"),
+            ("POST", "/bridge/v1/faces/groups/forget"),

 # tests/test_r3_seams.py::test_the_registry_lists_the_camera_and_faces_plugins_and_plugins_satisfy_the_port
-    assert [f.__name__ for f in PLUGINS] == ["camera_plugin", "create_plugin"]
+    assert [f.__name__ for f in PLUGINS] == ["camera_plugin", "create_plugin", "create_plugin"]

 # tests/test_r4_seams.py::test_the_two_photo_routes_are_allowed_and_nothing_else_changed
-    assert len(BRIDGE_ROUTES) == 9
+    assert len(BRIDGE_ROUTES) == 11

 # tests/test_r3_wiring.py::test_the_bridge_builds_every_plugin_with_its_environment
-    assert names == ["core", "camera", "faces"]
+    assert names == ["core", "camera", "faces", "facegroups"]

 # tests/test_home_api.py::test_link_then_status_then_unlink (the real bridge now reports 0.2.0)
-    assert body["parts"]["ha"] is True and body["bridge_version"] == "0.1.0"
+    assert body["parts"]["ha"] is True and body["bridge_version"] == "0.2.0"

 # tests/test_r11_wiring.py::test_the_helpers_start_with_four_empty_parts_and_both_composites
-        assert sorted(jobs) == sorted(j for p in PARTS for j in CLOCK_JOBS[p]), jobs
+        r111 = ["face_groups_poll", "photos_import"]  # + Part A's job names
+        assert sorted(jobs) == sorted([*(j for p in PARTS for j in CLOCK_JOBS[p]), *r111]), jobs

 # tests/test_r11_wiring.py::test_a_failing_part_is_left_empty_and_the_others_run
-        assert st.helpers_clock.job_names == ("bills_due",)
+        assert st.helpers_clock.job_names == ("bills_due", "photos_import", "face_groups_poll")
 ...
-        assert status is not None and status["jobs"] == {"bills_due": "ok"}
+        assert status is not None and status["jobs"]["bills_due"] == "ok"
```

### 3.3 Smaller things

- `api/r4_wiring.wire_photos` builds `PhotosService` without limits. This part sets them late
  (`facegroups/part.py` gives the service the owner's `photos_max_picked` and `photos_import_batch`
  whenever a route, a tool or a job asks for it). Passing
  `limits=ImportLimits(s.photos_max_picked, s.photos_import_batch)` there would make it true from
  the first call; until then a pick started by the chat tool before anything else has touched the
  part allows Google's 2,000 and the import itself enforces the owner's lower number.
- `console-home.js`: the "Your home kit is older than this JARVIS" sentence could name the step:
  `setup-windows.ps1 -Update`.
- `buildbook/gen/layers.py` has no layer for `facegroups` (nor `series`, `fixes`, `understand`,
  `picture`): `tests/test_book_gen_code.py::test_every_real_package_and_module_is_mapped_to_a_known_layer`
  already fails on `r11-1-i0` for that reason. `facegroups` is Layer 5.
- Guide card C61 says "PLANNED" for Part C; it is built. `scripts/arch_coverage.py` passes as is.
- `console-connectors.css` keeps the rules of the form this part removed from the Connectors card
  (`.cenrol`, `.crow`, `.ctick`): unused now, harmless, not this part's file.
- `evals/run_all_mock.py`: add `r11_1` (the brief says I1 does).
- `tests/test_r11_1_seams.py::test_the_eval_runner_passes_with_every_part_still_a_stub` needs "not
  built yet" in the runner's output; that stays true only while another part is a stub.

## 4. Existing tests changed on purpose

Nothing was weakened; each change follows a behaviour the plan changes.

| Test | Before | Now | Why |
|---|---|---|---|
| `tests/test_photos_picker.py` | `MAX_PICKED` (20) items listed; `maxItemCount: "20"` | one page of 100; `maxItemCount: "2000"`; new tests for paging, a bad page token and the owner's limit | O6 / D14 |
| `tests/test_photos_service.py` | `list_items` stubbed; both test photos identical bytes | `list_page` stubbed; each photo its own bytes, checked "each once" | O6: the list is paged and resumable |
| `tests/test_photos_edge.py::test_enrol_sends_ids_only` | enrol answer `{}` | `{"pictures": 4, "camera": "copied"}`, strictly parsed | O7: the route now exists and says two facts |
| `tests/photos_fakes.py` | one-page picker, enrol returns nothing | paged picker with `gone` and `max_items`; edge with `ready`, `groups`, `forget` | the fakes follow the ports |
| `tests/test_deploy_home.py` | bridge `mem_limit == "256m"`; `param([switch]$HaToken)` exactly | `768m`; the parameter list now starts with `$HaToken` (`-Update`, `-PhotosDir` follow; pinned whole in `test_r11_1_c_kit.py`) | O7: two models and a picture in memory; the kit's new steps |
| `tests/test_homebridge_core.py` | `bridge_version == "0.1.0"` | `== BRIDGE_VERSION` (0.2.0) | the kit's version rose so the cloud can tell an old kit |
| `tests/test_deploy_config.py` | (new test added) | the Picker API line and its warning | O5 |

## 5. For the owner: updating the kit and the photo folder

The home kit does **not** use Docker Desktop. Its own setup installed Ubuntu inside Windows (WSL2)
and runs Docker there, so you never open Docker Desktop for these steps; if you also have Docker
Desktop installed, leave it as it is. Everything below is typed in PowerShell on the laptop. I
could not run these steps on a real Windows laptop (see 7); the scripts behind them are tested on
Linux with stand-ins.

### (a) Update the home kit to this version

1. On the laptop, open JARVIS in the browser: **Integrations -> Home -> Download home kit**.
2. Right-click the downloaded zip -> **Extract All** -> choose `C:\` -> when Windows asks, choose
   **Replace the files in the destination**. (This is the folder `C:\JARVIS-Home`.)
3. Click Start, type `PowerShell`, right-click **Windows PowerShell** -> **Run as administrator**
   -> Yes.
4. Type these two lines, pressing Enter after each:

   ```
   cd C:\JARVIS-Home
   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -Update
   ```

5. Wait for the word **Updated.** It downloads two small model files once (about 40 MB), checks
   them, and restarts only the bridge. Your camera, passwords, Home Assistant token and link are
   kept.
6. In JARVIS, **Integrations -> Home** says Online again within two minutes, and the line "Your
   home kit is older than this JARVIS" is gone.

### (b) Choose the photo folder and set `PHOTOS_DIR`

1. Make one folder on the laptop for copies of photos, for example
   `C:\Users\<your name>\Pictures\JARVIS`. Keep it for photos only.
2. In File Explorer, hold **Shift**, right-click that folder, choose **Copy as path**.
3. In PowerShell as administrator (as in step 3 above):

   ```
   cd C:\JARVIS-Home
   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir "C:\Users\<your name>\Pictures\JARVIS"
   ```

   (Paste the path you copied in place of the one in quotes.) The script writes `PHOTOS_DIR` into
   `bridge.env` for you and restarts the bridge. You never edit the file by hand.
4. The bridge can only **read** that folder. It never changes, moves or deletes a photo.
5. Only JPEG photos (`.jpg`, `.jpeg`) are read. iPhone HEIC photos are skipped: on the iPhone set
   Settings -> Camera -> Formats -> **Most Compatible**, or export as JPEG.
6. A folder whose name has `$`, `#` or a quote mark in it is refused with a plain sentence:
   rename the folder and run the line again.

### (c) Free ways to get phone photos into that folder

JARVIS does not sync your phone; you bring the photos. All of these are free.

1. **USB cable (simplest).** Connect the phone to the laptop, unlock it, choose "File transfer" on
   the phone. In File Explorer open the phone -> `DCIM` -> `Camera`, select the photos, copy,
   paste into your folder.
2. **Google Takeout (a one-off export of what is in Google Photos).** Open
   `https://takeout.google.com`, press **Deselect all**, tick **Google Photos**, press "All photo
   albums included" to pick albums or years, **Next step**, "Export once", `.zip`, **Create
   export**. Google e-mails a download link (it can take hours). Download each zip, right-click ->
   Extract All, and copy the photos into your folder. The small `.json` files beside them are
   ignored.
3. **Google Photos in the browser (for a handful).** Open `https://photos.google.com`, select the
   photos, press **Shift + D**, extract the zip into your folder.
4. **Syncthing (keeps the folder filled by itself, over your own Wi-Fi, no cloud).** Free and open
   source. Install it on the laptop from `https://syncthing.net/downloads/` and share your phone's
   camera folder to the photo folder as "receive only". On Android the original Syncthing app was
   discontinued in December 2024; a community app continues it (Syncthing-Fork), and it has
   changed maintainers since, so check the Syncthing downloads page for the app it currently
   points to before installing one. There is no free official Syncthing for iPhone: use 1 to 3.
   I did not test Syncthing with the kit.
5. Or skip the folder: **Connectors -> Google Photos -> Choose photos** picks up to 2,000 at a
   time in Google's own picker and sends them to the laptop one at a time.

### (d) Check it worked, and switch it off

1. In JARVIS open **Faces**. Under **Unnamed groups** the last line reads "Watched photo folder:
   on, N pictures read so far." N grows by about 6 a minute (360 an hour).
2. A face that is in 3 or more photos appears there as "Group 4 · 23 photos" with **Name** and
   **Forget**.
3. To see **who** a group is, open `http://localhost:8098/faces` **on the laptop** (the code was
   printed by the setup script) -> "Faces from your photos". JARVIS itself never sees a face.
4. Press **Name**, choose "A new person" (the person must have agreed; for a child a parent or
   guardian) or someone you already added. From then on new photos of that person, and the
   camera, recognise them with nothing more to do.
5. If it says "The face reader on your laptop is off", run step (a) 4 again: the model files did
   not download.
6. **Switch the folder off:**

   ```
   cd C:\JARVIS-Home
   powershell -ExecutionPolicy Bypass -File .\setup-windows.ps1 -PhotosDir off
   ```

   Nothing in the folder is changed. Groups already found stay until you name or forget them, or
   for 90 days.
7. **Remove what was found:** Faces -> Unnamed groups -> **Forget** on a group, or **Privacy ->
   Faces -> Face groups -> Delete** for all of them. If the laptop is off it says "NOT done yet"
   and finishes when the laptop is back.

How long things take at the default settings (arithmetic, not measured on your laptop): a pick of
2,000 photos takes about 17 hours in the background (10 photos every 5 minutes); with the
Connectors panel left open it is stepped continuously and should take about an hour; a folder of
5,000 photos takes about 14 hours. `photos_import_batch` (up to 50) and `PHOTOS_PER_MINUTE` (up to
30) raise both.

## 6. Deviations from the plan

1. **The model files are downloaded and checked, not bundled in the kit.** SFace is 38.7 MB: the
   kit zip is served by Cloud Run (32 MB response limit) and the repository is public. The kit
   carries `models/MODELS.txt` (address, size, SHA-256, licence) and the two licence texts;
   `setup-wsl.sh models` downloads, verifies and keeps each file; the bridge verifies again and
   says "off" in plain words without them. The plan's "bundled; hash-locked" becomes "pinned;
   hash-locked; fetched once".
2. **A fourth bridge route, `POST /bridge/v1/faces/groups/forget`.** D21-C needs a delete that is
   confirmed by the laptop's own counts; none of the three planned routes can carry it.
3. **Naming and forgetting are panel actions, not gateway tools.** The brief's general rule is "a
   route that acts calls the tool through the gateway". The consent statement must come from your
   own hand, never from the model, which is how R3 built Faces (`api/faces.py` calls
   `FacesService` directly) and R4 built photo enrolment. This part follows that: the two tools
   (`faces_groups`, `photos_import_status`) only read, and the two actions write audit records
   themselves (`faces_group_name`, `faces_group_forget`: a count, never a name or an id).
4. **Expiry counts from when a group was first seen**, not last seen, so a face that keeps
   appearing still leaves after 90 days unless named (the stricter reading of D21-C).
5. **The Connectors card no longer names faces in place.** R4's "Name for face 1" form named a
   face you could not see. Naming now happens in one place, Faces -> Unnamed groups, where the
   laptop's page shows who it is. What changes for you: a face needs 3 photos before it can be
   named (it was 1). The route `/v1/connectors/photos/enrol` still exists and is tested.
6. **`score` on the wire is a mapped confidence**, not SFace's cosine: 0.9 is exactly the
   laptop's own threshold, so the cloud's existing 0.9 bar means the same thing as before.
7. **The 2026 YuNet model and the full SFace model**: the quantised SFace fails to load in OpenCV
   5.0 (`setMainGraphInput`), so the 38.7 MB file is used.
8. **Kit and bridge version 0.2.0; bridge memory 256 MB -> 768 MB.** The version lets the cloud
   tell "kit too old" from "laptop asleep".
9. **`setup-wsl.sh configure` no longer replaces this laptop's `bridge.env`, `frigate.env` or
   `images.env`** when the kit is extracted again: an update must keep your settings.
10. **The kit is WSL2 with its own Docker, not Docker Desktop** (the code's reality; the owner
    steps above are written for it).
11. An import can also be stepped from the panel (`POST /v1/facegroups/import/step`), so an open
    panel is not limited to the clock's pace. A Picker session that expires before anything was
    read still answers `no_session`, as before.

## 7. Not verified live

Everything above runs on fakes, on the real signed channel and bridge app in process, and (for
the engine) on the real model files with a face drawn in code. Not verified:

- The bridge image built by Docker with OpenCV inside `python:3.12-slim` (the two wheels were
  downloaded with `pip download --require-hashes` for x86-64 and ARM64 on Python 3.12 and passed
  the hash check, and `cv2` was seen to need only glibc, libgcc, libstdc++ and zlib; the image
  itself was not built).
- `setup-windows.ps1 -Update` and `-PhotosDir` on Windows (PowerShell was not available here);
  the WSL read-only mount of a `C:` folder for the bridge's user (uid 10001).
- Accuracy and the 0.42 match threshold on real faces: drawn faces all look alike to SFace, so
  grouping is tested with a scripted engine. Expect some people split into two groups (name the
  second as "someone already added") and, rarely, two people in one; `FACE_MATCH_SCORE` (0.30 to
  0.80) tunes it. Speed on the laptop is not measured.
- Frigate's face-library endpoint taking the copied crops (R3 already lists it unverified).
- Google's Picker in practice: session and link lifetimes, paging tokens, the 2,000 limit, and
  whether enabling `photospicker.googleapis.com` is all the project needs.
- EXIF orientation: metadata is stripped before the laptop sees a picked photo, so a photo Google
  serves sideways is read sideways and may miss a face.
- HEIC photos are skipped, not converted. Syncthing and Takeout were not tried with the kit.
- The 8-second cloud-to-laptop timeout with a real laptop reading a 2048 px photo.

## 8. Found on the way (not this part's to change)

- The Faces panel's dialog (R3) does not pass the visual gate's generic probes when measured
  open: its `h3` title has the browser's default margin and font and its Cancel / OK row has no
  gap. The gate never opened it before. This part added one field to it ("Who is this?") and its
  browser test reads the probes for that field only. `console-faces.css` / `console.css` would
  fix it.
- `tests/test_trust_flag.py::test_a_chat_request_carries_no_history_or_blocks` and
  `tests/test_book_gen_code.py::test_every_real_package_and_module_is_mapped_to_a_known_layer`
  fail on `r11-1-i0` itself.
- `create_local_app` (homebridge/local_page.py) was 130 lines before this part and is 134 now;
  `home/client.py::exchange` is 59. Both are older than the 50-line guard.

## 9. Commands run, and their last lines

```
/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_r11_1_*.py tests/test_photos_*.py \
    tests/test_homebridge_*.py tests/test_deploy_*.py tests/test_faces_*.py \
    tests/test_connectors_console.py tests/test_r51_console_assets_linked.py
        1033 passed, 2 skipped in 73.70s
/tmp/venv-b/bin/pytest -q -p no:cacheprovider tests/test_r11_1_seams.py tests/test_r1_seams.py \
    tests/test_r6_wiring_seams.py tests/test_arch_coverage.py tests/test_r51_console_assets_linked.py
        (with test_book_gen_snapshot, test_camera_events, test_home_link) 487 passed in 17.56s
/tmp/venv-b/bin/ruff check src tests evals scripts            All checks passed!
/tmp/venv-b/bin/ruff format --check src tests evals scripts   1393 files already formatted
/tmp/venv-b/bin/mypy src/jarvis/facegroups src/jarvis/homebridge src/jarvis/api/fix_photos.py
        Found 9 errors in 3 files (the 9 older ones: llm/anthropic_provider.py, core/window.py,
        memory/redis_store.py; none in this part's files)
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r11_1/run.py --mock --part photos
        photos: 14/14 cases passed
        r11_1: 14/14 passed; negative control failed the suite: True
PYTHONPATH=$PWD/src /tmp/venv-b/bin/python evals/r11_1/run.py --mock
        r11_1: 17/17 passed; negative control failed the suite: True
evals home_link 46/46, faces 38/38, r3_needles 15/15, r4_needles 8/8, privacy 61/61 (all with a
        failing control)
```

Also run: this part's tests on Python 3.13 (535 passed, 1 skipped) and on Python 3.12 under
coverage (584 passed; 93 % of `jarvis.facegroups`, `jarvis.photos`, `jarvis.homebridge` and
`api/fix_photos.py`, no module of this part below 87 %); the engine tests with the real model
files (`JARVIS_FACE_MODELS_DIR` set: 23 passed); `shellcheck -S warning deploy/cloudrun.sh
deploy/home/setup-wsl.sh` (clean); `scripts/arch_coverage.py` ("arch coverage: OK") and
`scripts/check_doc_versions.py` ("All 26 documents have their version line and change log.");
the kit builds (56 files, 137 KB, the six new bridge modules and `models/MODELS.txt` inside, no
model file).

Neighbouring suites run in chunks (home, camera, privacy, R3 / R4 / R11 seams and wiring,
permissions, notify, gateway, build-book): the only failures are the seven in 3.2 and the two in
8. The whole suite was not run (the brief leaves it to I1).

```
flock /tmp/r111-logs/heavy.lock /tmp/venv-b/bin/mypy src
        Found 9 errors in 3 files (checked 620 source files)
        (core/window.py 1, llm/anthropic_provider.py 7, memory/redis_store.py 1: the older ones)
flock /tmp/r111-logs/heavy.lock env JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src \
    /tmp/venv-c/bin/python -m pytest -q tests/browser/test_r11_1_c_photos.py -m browser
        15 passed in 129.77s
flock /tmp/r111-logs/heavy.lock env JARVIS_BROWSER_TESTS=1 PYTHONPATH=$PWD/src \
    /tmp/venv-c/bin/python -m pytest -q tests/browser -m browser -k "r11_1 or ui_audit"
        127 passed, 995 deselected in 400.08s
```

The browser test needed two corrections of the test itself before it was green, both found by
running it: the consent case provokes a 422 on purpose, which the browser logs as its one
console error; and the naming dialog was measured 300 ms after opening, exactly the length of
its entry animation, so on a busy machine the new field was once caught half-faded on Day. No
change to the console code came out of either.

## 10. For the security reviewer: look here first

1. **The consent door, twice.** Cloud: `facegroups/service.py::name` -> `photos/service.py::enrol`
   -> `faces/service.py::add` (`consent.check`); `name_existing` accepts only a person who already
   has `consent_at`. Bridge: `homebridge/face_groups.py::_enrol` refuses any person id that is not
   on the consent list the cloud sent (`no_consent`), and a named group whose person later loses
   consent names nobody.
2. **What crosses.** `photos/edge.py`: every bridge answer is parsed with `extra="forbid",
   strict=True`; anything more than ids, counts and a score is refused whole (`EdgeBadReply`) and
   nothing of it is stored or logged. `tests/test_r11_1_c_needles.py`.
3. **The 6 MB route.** `homebridge/app.py::_read`: megabytes are read only after
   `auth.plausible(header)` (a cheap check that the header could be this home's; the real
   signature is verified afterwards over the body), under a one-at-a-time lock, with a declared
   and a streamed cap. Is `plausible` strong enough against a caller who has seen one old header?
4. **The decoder.** `homebridge/jpeg.py` and `face_engine.py::reduction`: JPEG only, dimensions
   read from the header before `cv2.imdecode`, pixel caps, `OPENCV_IO_MAX_IMAGE_PIXELS` in the
   image. A hostile file in the watched folder is the realistic attack on a native decoder.
5. **The dynamic import** of `cv2` and `numpy` (`face_engine.py`, `RUNTIME_PACKAGES`): it exists
   to pass the kit's import allow-list, which is not this part's file (3.1).
6. **The model download.** `deploy/home/setup-wsl.sh::fetch_model`: fixed addresses at a pinned
   commit, SHA-256 and size checked before the file is kept, a mismatch deleted; `put_env` (how a
   value is written into `bridge.env`) and the character check on the photo folder's path.
7. **The watched folder.** `homebridge/face_folder.py`: `O_NOFOLLOW`, no symlinks, no dot
   folders, depth and size caps, read-only mount; nothing is ever written there.
8. **The laptop's page.** `homebridge/local_page.py::_group_routes`: the only place a crop is
   served; login, CSRF token on writes, Host and Origin checks as the R3 page.
9. **The store.** `homebridge/face_store.py`: SQLite, folder 0700, file 0600, `secure_delete`,
   parameterised queries; forget and expiry remove embeddings, crops and picture rows.
10. **Deletion honesty.** `facegroups/service.py::forget` / `forget_all` / `poll`: done only on
    the laptop's answer; names given while the laptop slept are delivered before any forget.

## Change log

| Version | Date | Release | What changed | By |
|---|---|---|---|---|
| v11.1.1 | 12 Nov 2026, 08:49 IST | R11.1 | First edition: what Part C built for O5, O6 and O7, the licences read, what I1 must add, the owner's steps for the kit and the photo folder, deviations, and what is not verified live | 🛠 Mark XV |
| v11.1.2 | 12 Nov 2026, 09:43 IST | R11.1 | The results that were waiting behind the builders' shared lock: `mypy src` in full (the 9 older errors only), this part's browser test (15 passed) and the brief's full browser command (127 passed); the two corrections the browser test needed | 🛠 Mark XV |
