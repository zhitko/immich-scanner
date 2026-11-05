# Backlog

Planning only. Nothing here is a promise, and none of it belongs in source comments.

Order inside each area is the order to do the work. P1 is what makes the owner's desk trustworthy. P2 is the next useful slice. P3 can wait.

## Scanner

- [ ] **P1.** Confirm a real Canon CanoScan LiDE 700F (`04a9:1907`, genesys) scans from the app container: `scanimage -L`, and a full-bed TIFF at 300 and 600 dpi. Record the device name and any option the backend actually requires.
- [ ] **P1.** After that scan, decide whether `--source` must be set to Flatbed. The transparency unit is on the same scanner, and the app currently leaves the source at the backend default because forcing it can fail.
- [ ] **P2.** Let the operator cancel a scan that is already in `scanimage`. Today a scan runs to completion.
- [ ] **P2.** Ship the udev rule as a file in the repo. It is only described in the README today.

## Detection and upload

- [ ] **P1.** Detect prints that have no usable edge against the lid. A white print on a white lid, or a black print on a black lid, is missed when flood fill walks through it. The person can draw a region; the detector should still do better on low-contrast edges.
- [ ] **P1.** Size the "about 5 mm" gap from the scan's dpi. The close kernel is a fraction of the downscaled image (`0.008` of the short side), so the same sheet behaves differently at 300 dpi and 600 dpi.
- [ ] **P1.** Follow the Immich asset-update API off the deprecated `PUT /api/assets/{id}` from the v3.3.5 spec. Newer releases add `PATCH` and intend to drop `PUT`. Keep the v3.3.5 call working, and select the method from the server version.
- [ ] **P2.** When a changed crop is uploaded, the previous Immich asset is left in place and a new one is created. Offer to remove the previous asset after the new one is stored, and say so before the upload.
- [x] **P2.** Optional per-photo retouch, after the crop and before upload. Run it on CPU. The target laptop has Intel integrated graphics and 64 GB of RAM, so one photo at a time is the budget, not a batch of the whole bed.
  - Upscale and denoise with a small Real-ESRGAN model.
  - Face restoration with CodeFormer or GFPGAN. These invent detail. Default them off, and label the preview as a reconstruction.
  - Optional colorization with DDColor, and optional scratch inpainting with LaMa. Both off unless chosen for that photo.
  - Keep the untouched crop on disk. Retouch writes a derivative. Upload sends the derivative only when the person picks it.
  - Ship weights outside git, and check each model's license before downloading it.
  - ONNX Runtime is the portable CPU path. OpenVINO is the optional Intel path. Measure both on the laptop before claiming the GPU is faster. The integrated GPU is not a discrete accelerator.

## UI

- [x] **P2.** Before/after preview for the retouch step above, with the original crop still one click away. The choice of what gets uploaded has to be visible on the photo, not buried in settings.
- [ ] **P2.** Nudge the selected region with the keyboard. Corner dragging on a trackpad is easy to overshoot, and the only fix today is to drag again.
- [ ] **P3.** Warn in the region list when a box overlaps another, including an already uploaded one.

## Infra / docs

- [ ] **P1.** Run the same path against a real Immich server at the version in the README (v3.3.5, or a newer one if the PUT/PATCH item lands first): upload, duplicate checksum, album add, description, date, GPS, and a failed upload that can be retried.
- [ ] **P2.** Keep the checked-in Immich contract pinned to a named release. When the target version changes, re-read that release's OpenAPI file rather than the docs on `main`.
- [ ] **P3.** Add a browser check to CI for the review desk. The current coverage is unit tests plus one manual pass against the mock.
