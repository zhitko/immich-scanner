import {
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { EMPTY, Observable, finalize, forkJoin, map, of, switchMap, tap } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import {
  Corner,
  Edge,
  HANDLE_GAP_PX,
  HANDLE_TOLERANCE_PX,
  Hit,
  Point,
  Rect,
  clampRect,
  corners,
  hitTest,
  movedRect,
  rectFromPoints,
  resizeFromEdge,
  resizeFromOpposite,
  rotationAngle,
  snapAngle,
  TOUCH_TOLERANCE_PX,
} from './geometry';
import { Album, Region, RegionMetadata, RetouchModel, ScanDetail } from './models';
import {
  chosenVersion,
  displayedAspect,
  formatPhotoFacts,
  PhotoVersion,
  previewCacheKey,
  shownVersion,
  uploadVersionLabel,
} from './preview';
import { formatStamp, fromDateAndTime, toDateAndTime } from './time';

interface Draft {
  takenDate: string;
  takenTime: string;
  description: string;
  albumId: string;
  latitude: string;
  longitude: string;
  favorite: boolean;
  rating: number | null;
  visibility: string;
}

type DragKind = 'move' | 'resize' | 'edge' | 'rotate' | 'draw';

interface Drag {
  id: string | null;
  kind: DragKind;
  corner: Corner | null;
  edge: Edge | null;
  originX: number;
  originY: number;
  start: Rect;
  current: Rect;
}

interface ActiveJob {
  id: string;
  type: 'detect' | 'upload' | 'retouch';
  status: string;
  error: string | null;
  regionId?: string;
}

type Section = 'preview' | 'retouch' | 'details';

const SECTION_KEY = 'immich-scanner.inspector-section';
const LOCATION_ERROR = 'Enter both latitude and longitude, or leave both empty.';
const MIN_DRAWN_PX = 12;
const DEFAULT_STROKE = '#f5f1e8';

@Component({
  selector: 'app-editor',
  imports: [RouterLink],
  templateUrl: './editor.html',
  host: {
    '(document:keydown)': 'onKey($event)',
    '(document:pointerup)': 'release()',
    '(document:pointercancel)': 'release()',
    '(window:blur)': 'release()',
  },
})
export class EditorPage {
  private readonly api = inject(ArchiveApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly scan = signal<ScanDetail | null>(null);
  private readonly scanIds = signal<string[]>([]);
  private readonly scanIndex = computed(() => this.scanIds().indexOf(this.scanId() ?? ''));
  readonly previousScanId = computed(() => this.scanIds()[this.scanIndex() - 1] ?? null);
  readonly nextScanId = computed(() =>
    this.scanIndex() < 0 ? null : (this.scanIds()[this.scanIndex() + 1] ?? null),
  );
  readonly selectedId = signal<string | null>(null);
  readonly draft = signal<Draft | null>(null);
  readonly albums = signal<Album[]>([]);
  readonly retouchModels = signal<RetouchModel[]>([]);
  readonly immichUrl = signal('');
  readonly error = signal('');
  readonly notice = signal('');
  readonly busy = signal(false);
  readonly dirty = signal(false);
  readonly drag = signal<Drag | null>(null);
  readonly cursor = signal('crosshair');
  readonly activeJob = signal<ActiveJob | null>(null);
  readonly ratings = [1, 2, 3, 4, 5];
  readonly openSection = signal<Section | null>(storedSection());
  readonly previewOpen = signal(false);
  /** The enlarged view follows the Retouched section only when opened from there. */
  readonly lightboxVersion = signal(false);
  /** Which frame is pressed. While held it shows the other version for comparison. */
  readonly holding = signal<'retouch' | 'lightbox' | null>(null);
  readonly formatStamp = formatStamp;

  readonly selected = computed<Region | null>(() => {
    const scan = this.scan();
    return scan?.regions.find((region) => region.id === this.selectedId()) ?? null;
  });
  readonly selectedIndex = computed(() => {
    const scan = this.scan();
    return scan ? scan.regions.findIndex((region) => region.id === this.selectedId()) : -1;
  });
  readonly pendingCount = computed(
    () => this.scan()?.regions.filter((region) => region.needs_upload).length ?? 0,
  );
  readonly jobRunning = computed(() => {
    const job = this.activeJob();
    return !!job && (job.status === 'queued' || job.status === 'running');
  });
  readonly detecting = computed(
    () => !!this.scan()?.detecting || (this.jobRunning() && this.activeJob()?.type === 'detect'),
  );
  readonly uploading = computed(
    () =>
      (this.jobRunning() && this.activeJob()?.type === 'upload') ||
      !!this.scan()?.regions.some((region) => region.upload_status === 'uploading'),
  );
  readonly retouching = computed(
    () =>
      (this.jobRunning() && this.activeJob()?.type === 'retouch') ||
      !!this.scan()?.regions.some((region) => this.retouchingRegion(region)),
  );

  private readonly canvas = viewChild<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly frame = viewChild<ElementRef<HTMLElement>>('frame');
  private readonly lightboxClose = viewChild<ElementRef<HTMLButtonElement>>('lightboxClose');
  private readonly scanId = signal<string | null>(null);
  private noticeTimer = 0;
  /** Bumped on local edits so an in-flight scan reload cannot roll them back. */
  private scanRevision = 0;

  constructor() {
    const destroyRef = inject(DestroyRef);
    const timer = window.setInterval(() => this.poll(), 1500);
    destroyRef.onDestroy(() => {
      window.clearInterval(timer);
      window.clearTimeout(this.noticeTimer);
    });
    this.route.paramMap.pipe(map((params) => params.get('id'))).subscribe((id) => {
      if (id) {
        this.scanId.set(id);
        this.scan.set(null);
        this.selectedId.set(null);
        this.draft.set(null);
        this.dirty.set(false);
        this.drag.set(null);
        this.activeJob.set(null);
        this.notice.set('');
        this.closePreview();
        this.load(id);
      }
    });
    effect((onCleanup) => {
      const frame = this.frame()?.nativeElement;
      if (!frame) {
        return;
      }
      const observer = new ResizeObserver(() => this.draw());
      observer.observe(frame);
      onCleanup(() => observer.disconnect());
    });
    effect(() => {
      this.scan();
      this.selectedId();
      this.drag();
      untracked(() => this.draw());
    });
    effect(() => {
      if (!this.selected() && this.previewOpen()) {
        this.previewOpen.set(false);
      }
    });
    effect(() => {
      const close = this.lightboxClose();
      if (this.previewOpen() && close) {
        close.nativeElement.focus();
      }
    });
    this.api.listAlbums().subscribe({
      next: (albums) => this.albums.set(albums),
      error: () => this.albums.set([]),
    });
    this.api.getSettings().subscribe({
      next: (settings) => this.immichUrl.set(settings.immich_base_url.replace(/\/+$/, '')),
      error: () => this.immichUrl.set(''),
    });
    this.api.retouchModels().subscribe({
      next: (models) => this.retouchModels.set(models),
      error: () => this.retouchModels.set([]),
    });
  }

  redraw(): void {
    this.draw();
  }

  originalUrl(region: Region): string {
    const scan = this.scan();
    return scan ? this.api.regionPreviewUrl(scan.id, region.id, previewCacheKey(region)) : '';
  }

  versionUrl(region: Region, version: PhotoVersion): string {
    const scan = this.scan();
    if (!scan) {
      return '';
    }
    if (version === 'retouch') {
      return this.api.retouchPreviewUrl(scan.id, region.id, region.retouch_version ?? '');
    }
    return this.api.regionPreviewUrl(scan.id, region.id, previewCacheKey(region));
  }

  /** The retouched bitmap is already upright. The crop is turned in the browser. */
  versionTurns(region: Region, version: PhotoVersion): number {
    return version === 'retouch' ? 0 : region.quarter_turns % 4;
  }

  versionAlt(region: Region, version: PhotoVersion): string {
    if (version === 'crop') {
      return 'Straightened crop';
    }
    return region.retouch_reconstructs_faces ? 'Retouched reconstruction' : 'Retouched crop';
  }

  /** Versions to stack in a frame. Both load up front so holding swaps without a flash. */
  frameVersions(region: Region): PhotoVersion[] {
    return region.retouch_ready ? ['crop', 'retouch'] : ['crop'];
  }

  /** What the Retouched section shows: the upload choice, or the other one while held. */
  retouchShown(region: Region): PhotoVersion {
    return shownVersion(chosenVersion(region), region.retouch_ready, this.holding() === 'retouch');
  }

  versionLabel(region: Region): string {
    return uploadVersionLabel(region);
  }

  versionName(version: PhotoVersion): string {
    return version === 'retouch' ? 'Retouched' : 'Original';
  }

  hold(where: 'retouch' | 'lightbox', event: PointerEvent): void {
    if (event.button !== 0 || (event.target as HTMLElement).closest('button')) {
      return;
    }
    event.preventDefault();
    this.holding.set(where);
  }

  release(): void {
    this.holding.set(null);
  }

  frameAspect(region: Region): number {
    return displayedAspect(region.width, region.height, region.quarter_turns);
  }

  /** Resolution, density, and print size for the version open in the lightbox. */
  photoFacts(region: Region): string {
    return formatPhotoFacts(region, this.scan()?.dpi ?? null, this.lightboxShown(region));
  }

  bedUrl(): string {
    const scan = this.scan();
    return scan ? this.api.scanPreviewUrl(scan.id) : '';
  }

  immichLink(region: Region): string {
    const base = this.immichUrl();
    return base && region.immich_asset_id ? `${base}/photos/${region.immich_asset_id}` : '';
  }

  knownAlbum(id: string): boolean {
    return this.albums().some((album) => album.id === id);
  }

  statusLabel(region: Region): string {
    switch (region.upload_status) {
      case 'uploaded':
        if (region.crop_changed) {
          return 'Crop changed';
        }
        return region.needs_upload ? 'Details changed' : 'Uploaded';
      case 'uploading':
        return 'Uploading…';
      case 'failed':
        return 'Failed';
      default:
        return 'Not uploaded';
    }
  }

  statusTone(region: Region): string {
    if (region.upload_status === 'failed') {
      return 'bad';
    }
    if (region.upload_status === 'uploading') {
      return 'busy';
    }
    if (region.upload_status === 'uploaded') {
      return region.needs_upload ? 'warn' : 'ok';
    }
    return '';
  }

  /** Local edits can be uploaded before they are saved; upload stores them first. */
  canUpload(region: Region): boolean {
    const scan = this.scan();
    if (!scan || scan.files_deleted || this.busy() || this.uploading()) {
      return false;
    }
    if (region.upload_source === 'retouch' && !region.retouch_ready) {
      return false;
    }
    return this.dirty() || region.needs_upload;
  }

  uploadLabel(region: Region): string {
    if (region.upload_status === 'uploading') {
      return 'Uploading…';
    }
    if (region.upload_status === 'failed') {
      return 'Retry upload';
    }
    if (region.upload_status === 'uploaded' && !region.needs_upload && !this.dirty()) {
      return 'Uploaded';
    }
    return 'Upload to Immich';
  }

  jobMessage(job: ActiveJob): string {
    if (job.status === 'failed') {
      if (job.type === 'detect') {
        return 'Detection failed.';
      }
      if (job.type === 'retouch') {
        return 'Retouch failed.';
      }
      return 'Some photos could not be uploaded.';
    }
    if (job.type === 'detect') {
      return 'Finding photos on the bed…';
    }
    if (job.type === 'retouch') {
      const region = this.scan()?.regions.find((candidate) => candidate.id === job.regionId);
      if (!region) {
        return job.status === 'queued'
          ? 'Waiting to retouch this photo…'
          : 'Retouching this photo…';
      }
      return this.retouchLine(region, false);
    }
    return 'Uploading to Immich…';
  }

  retouchPercent(): number | null {
    const regionId = this.activeJob()?.regionId;
    if (!regionId) {
      return null;
    }
    const region = this.scan()?.regions.find((candidate) => candidate.id === regionId);
    return region?.retouch_status === 'running' ? region.retouch_progress : null;
  }

  retouchBanner(region: Region): string {
    return this.retouchLine(region, false);
  }

  retouchButton(region: Region): string {
    return this.retouchLine(region, true);
  }

  private retouchLine(region: Region, compact: boolean): string {
    if (region.retouch_status === 'queued') {
      return compact ? 'Waiting…' : 'Waiting to retouch this photo…';
    }
    if (region.retouch_progress === null) {
      return compact ? 'Retouching…' : 'Retouching this photo…';
    }
    const name =
      region.retouch_stage ?? (compact ? 'Retouching' : 'Retouching this photo');
    return `${name}… ${region.retouch_progress}%`;
  }

  retouchingRegion(region: Region): boolean {
    return region.retouch_status === 'queued' || region.retouch_status === 'running';
  }

  retouchChosen(region: Region): boolean {
    return (
      region.retouch_upscale ||
      region.retouch_denoise ||
      region.retouch_faces ||
      region.retouch_colorize ||
      region.retouch_scratches ||
      region.retouch_color_balance ||
      region.retouch_contrast
    );
  }

  missingWeights(region: Region): string {
    const needed = new Set<string>();
    if (region.retouch_denoise) {
      needed.add('upscale');
    } else if (region.retouch_upscale) {
      needed.add('scale');
    }
    if (region.retouch_faces) {
      needed.add('faces');
      needed.add('face-detection');
    }
    if (region.retouch_colorize) {
      needed.add('colorize');
    }
    if (region.retouch_scratches) {
      needed.add('scratch-detection');
      needed.add('inpaint');
    }
    const missing = this.retouchModels().filter((model) => needed.has(model.id) && !model.present);
    if (!missing.length) {
      return '';
    }
    return missing.map((model) => `${model.filename} (${model.license_id})`).join(', ');
  }

  chooseVersion(source: 'crop' | 'retouch'): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region || region.upload_source === source) {
      return;
    }
    if (source === 'retouch' && !region.retouch_ready) {
      return;
    }
    this.run(this.api.patchRegion(scan.id, region.id, { upload_source: source }), (updated) =>
      this.replaceRegion(updated, true),
    );
  }

  setRetouch(
    flag:
      | 'retouch_upscale'
      | 'retouch_denoise'
      | 'retouch_faces'
      | 'retouch_colorize'
      | 'retouch_scratches'
      | 'retouch_color_balance'
      | 'retouch_contrast',
    checked: boolean,
  ): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region || region[flag] === checked) {
      return;
    }
    this.run(this.api.patchRegion(scan.id, region.id, { [flag]: checked }), (updated) =>
      this.replaceRegion(updated, true),
    );
  }

  runRetouch(): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region || !this.retouchChosen(region)) {
      this.error.set(
        'Choose at least one retouch stage for this photo.',
      );
      return;
    }
    if (this.dirty()) {
      this.error.set('Save the crop first. Retouch uses the saved crop.');
      return;
    }
    this.run(
      this.api.retouch(scan.id, region.id, {
        upscale: region.retouch_upscale,
        denoise: region.retouch_denoise,
        faces: region.retouch_faces,
        colorize: region.retouch_colorize,
        scratches: region.retouch_scratches,
        color_balance: region.retouch_color_balance,
        contrast: region.retouch_contrast,
      }),
      (result) => {
        this.replaceRegion(result.region, true);
        this.activeJob.set({
          id: result.job_id,
          type: 'retouch',
          status: 'queued',
          error: null,
          regionId: result.region.id,
        });
        this.error.set('');
      },
    );
  }

  setSectionOpen(section: Section, open: boolean): void {
    if (open) {
      this.openSection.set(section);
    } else if (this.openSection() === section) {
      this.openSection.set(null);
    } else {
      return;
    }
    localStorage.setItem(SECTION_KEY, this.openSection() ?? 'none');
  }

  select(id: string): void {
    if (id === this.selectedId()) {
      return;
    }
    this.run(this.flushDraft(), (ok) => {
      if (ok) {
        this.selectNow(id);
      }
    });
  }

  step(offset: number): void {
    const scan = this.scan();
    if (!scan?.regions.length) {
      return;
    }
    const index = this.selectedIndex();
    const next = (Math.max(0, index) + offset + scan.regions.length) % scan.regions.length;
    this.select(scan.regions[next].id);
  }

  navigateScan(id: string | null): void {
    if (!id || this.busy() || this.drag()) {
      return;
    }
    this.run(this.flushDraft(), (ok) => {
      if (ok) {
        void this.router.navigate(['/scans', id]);
      }
    });
  }

  updateDraft<K extends keyof Draft>(key: K, value: Draft[K]): void {
    const draft = this.draft();
    if (!draft) {
      return;
    }
    if (key === 'latitude' && typeof value === 'string') {
      const pair = parseCoordinatePair(value);
      if (pair) {
        this.draft.set({ ...draft, latitude: pair[0], longitude: pair[1] });
        this.dirty.set(true);
        return;
      }
    }
    this.draft.set({ ...draft, [key]: value });
    this.dirty.set(true);
  }

  setRating(score: number): void {
    const current = this.draft()?.rating ?? null;
    this.updateDraft('rating', current === score ? null : score);
  }

  onPointerDown(event: PointerEvent): void {
    const scan = this.scan();
    const point = this.pointFrom(event);
    if (!scan || !point || scan.files_deleted || this.busy() || event.button !== 0) {
      return;
    }
    const canvas = this.canvas()?.nativeElement;
    const tolerance = event.pointerType === 'mouse' ? HANDLE_TOLERANCE_PX : TOUCH_TOLERANCE_PX;
    const picked = pickRegion(scan.regions, point, this.scale(scan), this.selectedId(), tolerance);
    if (!picked) {
      canvas?.setPointerCapture(event.pointerId);
      const start = rectFromPoints(point, point, scan);
      this.drag.set({
        id: null,
        kind: 'draw',
        corner: null,
        edge: null,
        originX: point.x,
        originY: point.y,
        start,
        current: start,
      });
      return;
    }
    if (picked.region.id !== this.selectedId()) {
      if (this.dirty()) {
        this.select(picked.region.id);
        return;
      }
      this.selectNow(picked.region.id);
    }
    canvas?.setPointerCapture(event.pointerId);
    const start = rectOf(picked.region);
    this.drag.set({
      id: picked.region.id,
      kind: picked.hit.kind,
      corner: picked.hit.kind === 'resize' ? picked.hit.corner : null,
      edge: picked.hit.kind === 'edge' ? picked.hit.edge : null,
      originX: point.x,
      originY: point.y,
      start,
      current: start,
    });
  }

  onPointerMove(event: PointerEvent): void {
    const drag = this.drag();
    const scan = this.scan();
    const point = this.pointFrom(event);
    if (!scan || !point) {
      return;
    }
    if (!drag) {
      this.cursor.set(this.hoverCursor(scan, point));
      return;
    }
    const bounds = { width: scan.width, height: scan.height };
    const origin = { x: drag.originX, y: drag.originY };
    let current = drag.start;
    if (drag.kind === 'move') {
      current = movedRect(drag.start, origin, point, bounds);
    } else if (drag.kind === 'resize' && drag.corner) {
      current = clampRect(resizeFromOpposite(drag.start, drag.corner, point), bounds);
    } else if (drag.kind === 'edge' && drag.edge) {
      current = clampRect(resizeFromEdge(drag.start, drag.edge, point), bounds);
    } else if (drag.kind === 'rotate') {
      const raw = rotationAngle({ x: drag.start.centerX, y: drag.start.centerY }, point);
      current = { ...drag.start, angleDeg: snapAngle(raw, event.shiftKey ? 15 : null) };
    } else if (drag.kind === 'draw') {
      current = rectFromPoints(origin, point, bounds);
    }
    this.drag.set({ ...drag, current });
  }

  onPointerUp(): void {
    const drag = this.drag();
    const scan = this.scan();
    if (!drag || !scan) {
      return;
    }
    this.drag.set(null);
    const geometry = {
      center_x: drag.current.centerX,
      center_y: drag.current.centerY,
      width: drag.current.width,
      height: drag.current.height,
      angle_deg: drag.current.angleDeg,
    };
    if (drag.kind === 'draw') {
      const minimum = MIN_DRAWN_PX / this.scale(scan);
      if (drag.current.width < minimum || drag.current.height < minimum) {
        return;
      }
      this.run(this.flushDraft(), (ok) => {
        if (ok) {
          this.run(this.api.createRegion(scan.id, geometry), (region) => this.insertRegion(region));
        }
      });
      return;
    }
    if (!drag.id || sameRect(drag.start, drag.current)) {
      return;
    }
    this.run(this.api.patchRegion(scan.id, drag.id, geometry), (region) =>
      this.replaceRegion(region),
    );
  }

  cancelDrag(): void {
    if (this.drag()) {
      this.drag.set(null);
    }
  }

  onKey(event: KeyboardEvent): void {
    if (this.previewOpen()) {
      if (event.key === 'Escape') {
        event.preventDefault();
        this.closePreview();
      }
      return;
    }
    const target = event.target as HTMLElement | null;
    const typing = !!target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key.toLowerCase() === 's') {
      event.preventDefault();
      this.saveMetadata();
      return;
    }
    if (event.key === 'Escape') {
      this.cancelDrag();
      if (typing) {
        target?.blur();
      }
      return;
    }
    if (typing || modifier || event.altKey || this.busy()) {
      return;
    }
    switch (event.key) {
      case 'ArrowRight':
      case 'j':
        event.preventDefault();
        this.step(1);
        break;
      case 'ArrowLeft':
      case 'k':
        event.preventDefault();
        this.step(-1);
        break;
      case 'r':
        this.rotate(true);
        break;
      case 'R':
        this.rotate(false);
        break;
      case 'Delete':
      case 'Backspace':
        event.preventDefault();
        this.removeRegion();
        break;
    }
  }

  saveMetadata(): void {
    if (!this.dirty()) {
      return;
    }
    this.run(this.flushDraft(), (ok) => {
      if (ok) {
        this.flash('Saved locally.');
      }
    });
  }

  applyToAll(): void {
    const scan = this.scan();
    const draft = this.draft();
    const region = this.selected();
    if (!scan || !draft || !region) {
      return;
    }
    const others = scan.regions.filter((item) => item.id !== region.id);
    const metadata = metadataFrom(draft);
    if (metadata === null) {
      this.error.set(LOCATION_ERROR);
      return;
    }
    if (
      !others.length ||
      !window.confirm(`Copy the date, album, and location to the other ${others.length} photos?`)
    ) {
      return;
    }
    const shared = {
      taken_at: metadata.taken_at,
      album_id: metadata.album_id,
      latitude: metadata.latitude,
      longitude: metadata.longitude,
    };
    const work = this.flushDraft().pipe(
      switchMap((ok) =>
        ok ? forkJoin(others.map((item) => this.api.patchRegion(scan.id, item.id, shared))) : EMPTY,
      ),
    );
    this.run(work, (updated) => {
      for (const item of updated) {
        this.replaceRegion(item);
      }
      this.flash(`Copied to ${updated.length} photos.`);
    });
  }

  addRegion(): void {
    const scan = this.scan();
    if (!scan) {
      return;
    }
    const geometry = {
      center_x: scan.width / 2,
      center_y: scan.height / 2,
      width: Math.max(8, scan.width * 0.28),
      height: Math.max(8, scan.height * 0.22),
      angle_deg: 0,
    };
    this.run(
      this.flushDraft().pipe(
        switchMap((ok) => (ok ? this.api.createRegion(scan.id, geometry) : EMPTY)),
      ),
      (region) => this.insertRegion(region),
    );
  }

  removeRegion(): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region) {
      return;
    }
    const warning =
      region.upload_status === 'uploaded'
        ? `Remove photo ${region.position}? The copy already in Immich stays there.`
        : `Remove photo ${region.position} from this scan?`;
    if (!window.confirm(warning)) {
      return;
    }
    const index = this.selectedIndex();
    this.run(this.api.deleteRegion(scan.id, region.id), () => {
      this.noteEdit();
      this.scan.update((current) =>
        current
          ? {
              ...current,
              regions: current.regions.filter((item) => item.id !== region.id),
              region_count: Math.max(0, current.region_count - 1),
            }
          : current,
      );
      const regions = this.scan()?.regions ?? [];
      const next = regions[Math.min(index, regions.length - 1)] ?? null;
      this.dirty.set(false);
      this.selectNow(next?.id ?? null);
    });
  }

  openPreview(version = false): void {
    this.lightboxVersion.set(version);
    this.holding.set(null);
    this.previewOpen.set(true);
  }

  /** Opened from Preview it starts on the crop, from Retouched on the upload choice. */
  lightboxShown(region: Region): PhotoVersion {
    const base = this.lightboxVersion() ? chosenVersion(region) : 'crop';
    return shownVersion(base, region.retouch_ready, this.holding() === 'lightbox');
  }

  closePreview(): void {
    this.holding.set(null);
    this.previewOpen.set(false);
  }

  /**
   * Clicks on the enlarged photo must not dismiss the dialog. Escape is left
   * to bubble so the dialog's own handler still closes it.
   */
  keepLightboxOpen(event: Event): void {
    if (event instanceof KeyboardEvent && event.key === 'Escape') {
      return;
    }
    event.stopPropagation();
  }

  rotate(clockwise: boolean): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region || scan.files_deleted) {
      return;
    }
    this.run(this.api.rotateRegion(scan.id, region.id, clockwise), (updated) =>
      this.replaceRegion(updated),
    );
  }

  redetect(): void {
    const scan = this.scan();
    if (!scan) {
      return;
    }
    const message = scan.regions.some((region) => region.upload_status === 'uploaded')
      ? 'Find the photos again? Photos that are not uploaded yet are replaced; uploaded ones stay.'
      : 'Find the photos again? Your current boxes and their details are replaced.';
    if (!window.confirm(message)) {
      return;
    }
    this.dirty.set(false);
    this.run(this.api.detect(scan.id), (job) =>
      this.activeJob.set({ id: job.job_id, type: 'detect', status: 'queued', error: null }),
    );
  }

  upload(regionId?: string): void {
    const scan = this.scan();
    if (!scan) {
      return;
    }
    const work = this.flushDraft().pipe(
      switchMap((ok) => (ok ? this.api.upload(scan.id, regionId ? [regionId] : undefined) : EMPTY)),
    );
    this.run(work, (job) => {
      this.error.set('');
      this.activeJob.set({ id: job.job_id, type: 'upload', status: 'queued', error: null });
    });
  }

  deleteScan(): void {
    const scan = this.scan();
    if (!scan || !window.confirm('Delete this scan, its photos, and the image files?')) {
      return;
    }
    this.run(this.api.deleteScan(scan.id), () => void this.router.navigate(['/scans']));
  }

  dismissError(): void {
    this.error.set('');
  }

  private run<T>(work: Observable<T>, done: (value: T) => void): void {
    this.busy.set(true);
    work.pipe(finalize(() => this.busy.set(false))).subscribe({
      next: (value) => done(value),
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.draw();
      },
    });
  }

  /** Save the open form, if it changed. Emits false when the form is invalid. */
  private flushDraft(): Observable<boolean> {
    const scan = this.scan();
    const region = this.selected();
    const draft = this.draft();
    if (!scan || !region || !draft || !this.dirty()) {
      return of(true);
    }
    const metadata = metadataFrom(draft);
    if (metadata === null) {
      this.error.set(LOCATION_ERROR);
      return of(false);
    }
    return this.api.patchRegion(scan.id, region.id, metadata).pipe(
      tap((updated) => this.replaceRegion(updated)),
      map(() => true),
    );
  }

  private selectNow(id: string | null): void {
    const region = this.scan()?.regions.find((item) => item.id === id) ?? null;
    this.selectedId.set(region?.id ?? null);
    this.draft.set(region ? draftFrom(region) : null);
    this.dirty.set(false);
  }

  private insertRegion(region: Region): void {
    this.noteEdit();
    this.scan.update((current) => {
      if (!current) {
        return current;
      }
      if (current.regions.some((item) => item.id === region.id)) {
        return {
          ...current,
          regions: current.regions.map((item) => (item.id === region.id ? region : item)),
        };
      }
      return {
        ...current,
        regions: [...current.regions, region],
        region_count: current.region_count + 1,
      };
    });
    this.selectNow(region.id);
  }

  private flash(message: string): void {
    this.notice.set(message);
    window.clearTimeout(this.noticeTimer);
    this.noticeTimer = window.setTimeout(() => this.notice.set(''), 3500);
  }

  private load(id: string): void {
    this.error.set('');
    const revision = this.scanRevision;
    this.api.getScan(id).subscribe({
      next: (scan) => {
        if (revision !== this.scanRevision || this.scanId() !== id) {
          return;
        }
        this.applyScan(scan);
        // Keep the review/history order stable while working through this list.
        if (!this.scanIds().includes(id)) {
          this.api.listScans(scan.upload_state === 'complete' ? 'uploaded' : 'open').subscribe({
            next: (scans) => {
              if (this.scanId() === id) {
                this.scanIds.set(scans.map((item) => item.id));
              }
            },
            error: (error: unknown) => {
              if (this.scanId() === id) {
                this.error.set(httpError(error));
              }
            },
          });
        }
      },
      error: (error: unknown) => {
        if (this.scanId() === id) {
          this.error.set(httpError(error));
        }
      },
    });
  }

  private reload(): void {
    const id = this.scanId();
    if (!id || this.drag()) {
      return;
    }
    const revision = this.scanRevision;
    this.api.getScan(id).subscribe({
      next: (scan) => {
        if (revision !== this.scanRevision || this.scanId() !== id) {
          return;
        }
        this.applyScan(scan);
      },
      error: () => undefined,
    });
  }

  private applyScan(scan: ScanDetail): void {
    this.scan.set(scan);
    const selected = scan.regions.find((region) => region.id === this.selectedId());
    if (selected) {
      if (!this.dirty()) {
        this.draft.set(draftFrom(selected));
      }
      return;
    }
    this.dirty.set(false);
    this.selectNow(scan.regions[0]?.id ?? null);
  }

  private replaceRegion(region: Region, keepDraft = false): void {
    this.noteEdit();
    this.scan.update((scan) =>
      scan
        ? { ...scan, regions: scan.regions.map((item) => (item.id === region.id ? region : item)) }
        : scan,
    );
    if (this.selectedId() === region.id && !(keepDraft && this.dirty())) {
      this.draft.set(draftFrom(region));
      this.dirty.set(false);
    }
    this.error.set('');
  }

  private noteEdit(): void {
    this.scanRevision += 1;
  }

  private poll(): void {
    const job = this.activeJob();
    if (job && this.jobRunning()) {
      this.api.getJob(job.id).subscribe({
        next: (next) => {
          if (this.activeJob()?.id !== job.id) {
            return;
          }
          const done = next.status === 'finished' || next.status === 'failed';
          this.activeJob.set({ ...job, status: next.status, error: next.error });
          this.reload();
          if (!done) {
            return;
          }
          if (next.status === 'failed') {
            this.error.set(next.error ?? this.jobMessage({ ...job, status: 'failed' }));
          } else {
            this.activeJob.set(null);
            this.flash(finishedLabel(job.type));
          }
        },
        error: () => undefined,
      });
      return;
    }
    if (this.detecting() || this.uploading() || this.retouching()) {
      this.reload();
    }
  }

  private hoverCursor(scan: ScanDetail, point: Point): string {
    if (scan.files_deleted) {
      return 'default';
    }
    const picked = pickRegion(scan.regions, point, this.scale(scan), this.selectedId());
    if (!picked) {
      return 'crosshair';
    }
    if (picked.hit.kind === 'rotate') {
      return 'grab';
    }
    if (picked.hit.kind === 'resize') {
      return picked.hit.corner === 'nw' || picked.hit.corner === 'se'
        ? 'nwse-resize'
        : 'nesw-resize';
    }
    if (picked.hit.kind === 'edge') {
      return edgeCursor(picked.region.angle_deg, picked.hit.edge);
    }
    return 'move';
  }

  private pointFrom(event: PointerEvent): Point | null {
    const canvas = this.canvas()?.nativeElement;
    const scan = this.scan();
    if (!canvas || !scan) {
      return null;
    }
    const bounds = canvas.getBoundingClientRect();
    if (bounds.width === 0 || bounds.height === 0) {
      return null;
    }
    return {
      x: ((event.clientX - bounds.left) / bounds.width) * scan.width,
      y: ((event.clientY - bounds.top) / bounds.height) * scan.height,
    };
  }

  private scale(scan: ScanDetail): number {
    const canvas = this.canvas()?.nativeElement;
    if (!canvas || scan.width === 0) {
      return 1;
    }
    const bounds = canvas.getBoundingClientRect();
    return bounds.width / scan.width || 1;
  }

  private draw(): void {
    const canvas = this.canvas()?.nativeElement;
    const scan = this.scan();
    if (!canvas || !scan) {
      return;
    }
    const bounds = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    if (
      canvas.width !== Math.round(width * ratio) ||
      canvas.height !== Math.round(height * ratio)
    ) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    const scale = width / scan.width;
    const drag = this.drag();
    const shapes: { region: Region | null; rect: Rect }[] = scan.regions.map((region) => ({
      region,
      rect: drag?.id === region.id ? drag.current : rectOf(region),
    }));
    if (drag?.kind === 'draw') {
      shapes.push({ region: null, rect: drag.current });
    }

    context.beginPath();
    context.rect(0, 0, width, height);
    for (const { rect } of shapes) {
      tracePath(context, rect, scale);
    }
    context.fillStyle = 'rgba(14, 12, 10, 0.42)';
    context.fill('evenodd');

    for (const { region, rect } of shapes) {
      if (region) {
        drawRegion(context, region, rect, scale, region.id === this.selectedId());
      } else {
        drawNew(context, rect, scale);
      }
    }
  }
}

function finishedLabel(type: ActiveJob['type']): string {
  if (type === 'detect') {
    return 'Detection finished.';
  }
  if (type === 'retouch') {
    return 'Retouch finished.';
  }
  return 'Upload finished.';
}

function storedSection(): Section | null {
  const value = localStorage.getItem(SECTION_KEY);
  if (value === 'none') {
    return null;
  }
  if (value === 'details' || value === 'retouch') {
    return value;
  }
  return 'preview';
}

function rectOf(region: Region): Rect {
  return {
    centerX: region.center_x,
    centerY: region.center_y,
    width: region.width,
    height: region.height,
    angleDeg: region.angle_deg,
  };
}

function sameRect(a: Rect, b: Rect): boolean {
  return (
    a.centerX === b.centerX &&
    a.centerY === b.centerY &&
    a.width === b.width &&
    a.height === b.height &&
    a.angleDeg === b.angleDeg
  );
}

function draftFrom(region: Region): Draft {
  const taken = toDateAndTime(region.taken_at);
  return {
    takenDate: taken.date,
    takenTime: taken.time,
    description: region.description,
    albumId: region.album_id ?? '',
    latitude: region.latitude === null ? '' : String(region.latitude),
    longitude: region.longitude === null ? '' : String(region.longitude),
    favorite: region.is_favorite,
    rating: region.rating,
    visibility: region.visibility ?? '',
  };
}

function metadataFrom(draft: Draft): RegionMetadata | null {
  const latitude = draft.latitude.trim();
  const longitude = draft.longitude.trim();
  if ((latitude === '') !== (longitude === '')) {
    return null;
  }
  const lat = latitude === '' ? null : Number(latitude);
  const lon = longitude === '' ? null : Number(longitude);
  if (
    (lat !== null && (Number.isNaN(lat) || Math.abs(lat) > 90)) ||
    (lon !== null && (Number.isNaN(lon) || Math.abs(lon) > 180))
  ) {
    return null;
  }
  const visibility = draft.visibility;
  return {
    taken_at: fromDateAndTime(draft.takenDate, draft.takenTime),
    description: draft.description,
    album_id: draft.albumId || null,
    latitude: lat,
    longitude: lon,
    is_favorite: draft.favorite,
    rating: draft.rating,
    visibility:
      visibility === 'timeline' || visibility === 'archive' || visibility === 'hidden'
        ? visibility
        : null,
  };
}

/** "48.85, 2.35" pasted into the latitude field, as copied from a map. */
function parseCoordinatePair(value: string): [string, string] | null {
  const match = /^\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*$/.exec(value);
  return match ? [match[1], match[2]] : null;
}

function pickRegion(
  regions: Region[],
  point: Point,
  scale: number,
  selectedId: string | null,
  tolerancePx?: number,
): { region: Region; hit: Hit } | null {
  const selected = regions.find((region) => region.id === selectedId);
  if (selected) {
    const hit = hitTest(rectOf(selected), point, scale, true, tolerancePx);
    if (hit) {
      return { region: selected, hit };
    }
  }
  for (const region of [...regions].reverse()) {
    const hit = hitTest(rectOf(region), point, scale, false);
    if (hit?.kind === 'move') {
      return { region, hit };
    }
  }
  return null;
}

function tracePath(context: CanvasRenderingContext2D, rect: Rect, scale: number): void {
  const points = corners(rect);
  context.moveTo(points[0].x * scale, points[0].y * scale);
  for (const point of points.slice(1)) {
    context.lineTo(point.x * scale, point.y * scale);
  }
  context.closePath();
}

function drawRegion(
  context: CanvasRenderingContext2D,
  region: Region,
  rect: Rect,
  scale: number,
  selected: boolean,
): void {
  const color = strokeColor(region, selected);
  context.save();
  context.translate(rect.centerX * scale, rect.centerY * scale);
  context.rotate((rect.angleDeg * Math.PI) / 180);
  const halfW = (rect.width / 2) * scale;
  const halfH = (rect.height / 2) * scale;
  context.setLineDash(region.crop_changed ? [7, 5] : []);
  context.lineWidth = selected ? 5 : 3.5;
  context.strokeStyle = 'rgba(0, 0, 0, 0.45)';
  context.strokeRect(-halfW, -halfH, halfW * 2, halfH * 2);
  context.lineWidth = selected ? 2.5 : 1.75;
  context.strokeStyle = color;
  context.strokeRect(-halfW, -halfH, halfW * 2, halfH * 2);
  if (selected) {
    context.setLineDash([]);
    context.beginPath();
    context.moveTo(0, -halfH);
    context.lineTo(0, -halfH - HANDLE_GAP_PX);
    context.stroke();
    fillHandle(context, 0, -halfH - HANDLE_GAP_PX, color, true);
    fillEdgeHandle(context, 0, -halfH, halfW * 2, color, true);
    fillEdgeHandle(context, halfW, 0, halfH * 2, color, false);
    fillEdgeHandle(context, 0, halfH, halfW * 2, color, true);
    fillEdgeHandle(context, -halfW, 0, halfH * 2, color, false);
    for (const [x, y] of [
      [-halfW, -halfH],
      [halfW, -halfH],
      [halfW, halfH],
      [-halfW, halfH],
    ]) {
      fillHandle(context, x, y, color, false);
    }
  }
  context.restore();

  const [topLeft] = corners(rect);
  const x = topLeft.x * scale + 4;
  const y = topLeft.y * scale + 4;
  const label = String(region.position);
  context.font = '600 12px system-ui, sans-serif';
  const badge = Math.max(20, context.measureText(label).width + 10);
  context.fillStyle = color === DEFAULT_STROKE ? 'rgba(20, 18, 15, 0.82)' : color;
  context.beginPath();
  context.roundRect(x, y, badge, 20, 10);
  context.fill();
  context.fillStyle = '#fff';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(label, x + badge / 2, y + 10.5);
}

function drawNew(context: CanvasRenderingContext2D, rect: Rect, scale: number): void {
  context.save();
  context.setLineDash([6, 4]);
  context.lineWidth = 2;
  context.strokeStyle = '#ffd166';
  context.strokeRect(
    (rect.centerX - rect.width / 2) * scale,
    (rect.centerY - rect.height / 2) * scale,
    rect.width * scale,
    rect.height * scale,
  );
  context.restore();
}

function fillEdgeHandle(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  edgeLength: number,
  color: string,
  alongWidth: boolean,
): void {
  const long = Math.min(22, Math.max(8, edgeLength * 0.22));
  const short = 6;
  const width = alongWidth ? long : short;
  const height = alongWidth ? short : long;
  context.setLineDash([]);
  context.fillStyle = '#fff';
  context.strokeStyle = color;
  context.lineWidth = 2;
  context.beginPath();
  context.roundRect(x - width / 2, y - height / 2, width, height, 3);
  context.fill();
  context.stroke();
}

function fillHandle(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  color: string,
  rotate: boolean,
): void {
  context.setLineDash([]);
  context.fillStyle = rotate ? color : '#fff';
  context.strokeStyle = rotate ? '#fff' : color;
  context.lineWidth = 2;
  context.beginPath();
  context.arc(x, y, rotate ? 7 : 6, 0, Math.PI * 2);
  context.fill();
  context.stroke();
}

/** Bidirectional resize cursor for an edge, following the print's rotation. */
function edgeCursor(angleDeg: number, edge: Edge): string {
  const axis = edge === 'e' || edge === 'w' ? angleDeg : angleDeg + 90;
  const wrapped = ((axis % 180) + 180) % 180;
  if (wrapped < 22.5 || wrapped >= 157.5) {
    return 'ew-resize';
  }
  if (wrapped < 67.5) {
    return 'nwse-resize';
  }
  if (wrapped < 112.5) {
    return 'ns-resize';
  }
  return 'nesw-resize';
}

function strokeColor(region: Region, selected: boolean): string {
  if (region.upload_status === 'failed') {
    return '#e05252';
  }
  if (region.crop_changed || (region.upload_status === 'uploaded' && region.needs_upload)) {
    return '#f0a030';
  }
  if (region.upload_status === 'uploaded') {
    return '#2fbf8f';
  }
  return selected ? '#4da3ff' : DEFAULT_STROKE;
}
