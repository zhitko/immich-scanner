# Backlog

Planning only. Nothing here is a promise, and none of it belongs in source comments.

Order inside each area is the order to do the work. P1 is what makes the owner's desk trustworthy. P2 is the next useful slice. P3 can wait.

## Client

- [ ] **P1.** Confirm a real Canon CanoScan LiDE 700F (`04a9:1907`, genesys) scans from the agent container: `scanimage -L`, a full-bed TIFF at 300 and 600 dpi, and the upload to the home server. Record the device name and any option the backend actually requires.
- [ ] **P1.** After that scan, decide whether `--source` must be set to Flatbed. The transparency unit is on the same scanner, and the agent currently leaves the source at the backend default because forcing it can fail.
- [ ] **P2.** Let the operator cancel a scan that is already in `scanimage`. Today the agent runs one scan to completion.
- [ ] **P2.** Ship the udev rule as a file in the repo. It is only described in the README today.
- [ ] **P3.** Add a test that the client's multipart upload (`file`, `dpi`, `device_name`, `filename`, `X-Scanner-Token`) still matches what the server accepts. The two apps are separate packages and can drift.

## Server

- [ ] **P1.** Detect prints that have no usable edge against the lid. A white print on a white lid, or a black print on a black lid, is missed when flood fill walks through it. The person can draw a region; the detector should still do better on low-contrast edges.
- [ ] **P1.** Stop a new detection from sitting on top of a region that was already uploaded. Re-running detection keeps uploaded regions and replaces the rest, so the new boxes can overlap the old ones.
- [ ] **P1.** Size the "about 5 mm" gap from the scan's dpi. The close kernel is a fraction of the downscaled image (`0.008` of the short side), so the same sheet behaves differently at 300 dpi and 600 dpi.
- [ ] **P1.** Follow the Immich asset-update API off the deprecated `PUT /api/assets/{id}` from the v3.3.5 spec. Newer releases add `PATCH` and intend to drop `PUT`. Keep the v3.3.5 call working, and select the method from the server version.
- [ ] **P2.** When a changed crop is uploaded, the previous Immich asset is left in place and a new one is created. Offer to remove the previous asset after the new one is stored, and say so before the upload.
- [ ] **P2.** `minAreaRect` often swaps width and height and shifts the angle by about 90°. The crop is then sideways until someone presses Rotate 90°. Pick a stable orientation at detection time and keep the manual turn.
- [ ] **P2.** Give the worker more than one thread only if a real scan shows detection or upload blocking the API. One thread is a deliberate limit, not an accident. A second thread is enough for this machine; do not add Redis for it.
- [ ] **P2.** Optional per-photo retouch, after the crop and before upload. Run it on CPU. The target laptop has Intel integrated graphics and 64 GB of RAM, so one photo at a time is the budget, not a batch of the whole bed.
  - Upscale and denoise with a small Real-ESRGAN model.
  - Face restoration with CodeFormer or GFPGAN. These invent detail. Default them off, and label the preview as a reconstruction.
  - Optional colorization with DDColor, and optional scratch inpainting with LaMa. Both off unless chosen for that photo.
  - Keep the untouched crop on disk. Retouch writes a derivative. Upload sends the derivative only when the person picks it.
  - Ship weights outside git, and check each model's license before downloading it.
  - ONNX Runtime is the portable CPU path. OpenVINO is the optional Intel path. Measure both on the laptop before claiming the GPU is faster. The integrated GPU is not a discrete accelerator.
- [ ] **P3.** Measure memory on a 600 dpi full-bed TIFF. Detection already downscales, but cropping loads the original. Document the ceiling for the home server, which may have much less RAM than the laptop.
- [ ] **P3.** The Immich API key is stored in SQLite and returned in full by the settings API. That matches a LAN appliance. It should stop being a cleartext field once the desk has login.

## UI

- [ ] **P1.** Add login for the review desk. Today every route except ingest is open, and ingest only checks `X-Scanner-Token`. A single local account is enough. Do not expose the desk to the internet and then rely on the token.
- [ ] **P2.** Before/after preview for the retouch step above, with the original crop still one click away. The choice of what gets uploaded has to be visible on the photo, not buried in settings.
- [ ] **P2.** Apply one date and one album to every photo on a sheet. A bed is usually one envelope, not twelve separate events.
- [ ] **P2.** Nudge the selected region with the keyboard. Corner dragging on a trackpad is easy to overshoot, and the only fix today is to drag again.
- [ ] **P3.** Warn in the region list when a box overlaps another, including an already uploaded one.

## Infra / docs

- [ ] **P1.** Run the same path against a real Immich server at the version in the README (v3.3.5, or a newer one if the PUT/PATCH item lands first): upload, duplicate checksum, album add, description, date, GPS, and a failed upload that can be retried.
- [ ] **P2.** Keep the checked-in Immich contract pinned to a named release. When the target version changes, re-read that release's OpenAPI file rather than the docs on `main`.
- [ ] **P3.** Add a browser check to CI for the review desk. The current coverage is unit tests plus one manual pass against the mock.
