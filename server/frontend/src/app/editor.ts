import {
  Component,
  DestroyRef,
  ElementRef,
  effect,
  inject,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { map } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import {
  Corner,
  HANDLE_GAP_PX,
  Rect,
  clampRect,
  hitTest,
  movedRect,
  resizeFromOpposite,
  rotationAngle,
} from './geometry';
import { Album, Region, RegionMetadata, ScanDetail } from './models';
import { fromDatetimeLocal, toDatetimeLocal } from './time';

interface Draft {
  takenAt: string;
  description: string;
  albumId: string;
  latitude: string;
  longitude: string;
  favorite: boolean;
  rating: string;
  visibility: string;
}

interface Drag {
  id: string;
  kind: 'move' | 'resize' | 'rotate';
  corner: Corner | null;
  originX: number;
  originY: number;
  start: Rect;
  current: Rect;
}

@Component({
  selector: 'app-editor',
  imports: [RouterLink],
  templateUrl: './editor.html',
})
export class EditorPage {
  private readonly api = inject(ArchiveApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  readonly scan = signal<ScanDetail | null>(null);
  readonly selectedId = signal<string | null>(null);
  readonly draft = signal<Draft | null>(null);
  readonly albums = signal<Album[]>([]);
  readonly error = signal('');
  readonly notice = signal('');
  readonly busy = signal(false);
  readonly dirty = signal(false);
  readonly drag = signal<Drag | null>(null);
  readonly activeJob = signal<{ id: string; status: string; error: string | null } | null>(null);
  readonly ratings = [1, 2, 3, 4, 5];

  private readonly canvas = viewChild<ElementRef<HTMLCanvasElement>>('canvas');
  private readonly frame = viewChild<ElementRef<HTMLElement>>('frame');
  private readonly scanId = signal<string | null>(null);

  constructor() {
    const destroyRef = inject(DestroyRef);
    const timer = window.setInterval(() => this.poll(), 1500);
    destroyRef.onDestroy(() => window.clearInterval(timer));
    this.route.paramMap.pipe(map((params) => params.get('id'))).subscribe((id) => {
      if (id) {
        this.scanId.set(id);
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
    this.api.listAlbums().subscribe({
      next: (albums) => this.albums.set(albums),
      error: () => this.albums.set([]),
    });
  }

  selected(): Region | null {
    const scan = this.scan();
    if (!scan) {
      return null;
    }
    return scan.regions.find((region) => region.id === this.selectedId()) ?? null;
  }

  redraw(): void {
    this.draw();
  }

  previewUrl(region: Region): string {
    const scan = this.scan();
    return scan ? this.api.regionPreviewUrl(scan.id, region.id, region.updated_at) : '';
  }

  bedUrl(): string {
    const scan = this.scan();
    return scan ? this.api.scanPreviewUrl(scan.id) : '';
  }

  knownAlbum(id: string): boolean {
    return this.albums().some((album) => album.id === id);
  }

  select(id: string): void {
    if (this.dirty() && !window.confirm('Discard unsaved photo details?')) {
      return;
    }
    const region = this.scan()?.regions.find((item) => item.id === id);
    this.selectedId.set(id);
    this.dirty.set(false);
    this.draft.set(region ? draftFrom(region) : null);
  }

  updateDraft<K extends keyof Draft>(key: K, value: Draft[K]): void {
    const draft = this.draft();
    if (!draft) {
      return;
    }
    this.draft.set({ ...draft, [key]: value });
    this.dirty.set(true);
  }

  onPointerDown(event: PointerEvent): void {
    const scan = this.scan();
    const point = this.pointFrom(event);
    if (!scan || !point || scan.files_deleted) {
      return;
    }
    const scale = this.scale(scan);
    const picked = pickRegion(scan.regions, point, scale, this.selectedId());
    if (!picked) {
      return;
    }
    if (picked.region.id !== this.selectedId()) {
      this.select(picked.region.id);
      if (this.selectedId() !== picked.region.id) {
        return;
      }
    }
    const canvas = this.canvas()?.nativeElement;
    canvas?.setPointerCapture(event.pointerId);
    const start = rectOf(picked.region);
    this.drag.set({
      id: picked.region.id,
      kind: picked.hit.kind,
      corner: picked.hit.kind === 'resize' ? (picked.hit.corner ?? null) : null,
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
    if (!drag || !scan || !point) {
      return;
    }
    const bounds = { width: scan.width, height: scan.height };
    let current = drag.start;
    if (drag.kind === 'move') {
      current = movedRect(drag.start, { x: drag.originX, y: drag.originY }, point, bounds);
    } else if (drag.kind === 'resize' && drag.corner) {
      current = clampRect(resizeFromOpposite(drag.start, drag.corner, point), bounds);
    } else if (drag.kind === 'rotate') {
      current = {
        ...drag.start,
        angleDeg: rotationAngle({ x: drag.start.centerX, y: drag.start.centerY }, point),
      };
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
    this.busy.set(true);
    this.api
      .patchRegion(scan.id, drag.id, {
        center_x: drag.current.centerX,
        center_y: drag.current.centerY,
        width: drag.current.width,
        height: drag.current.height,
        angle_deg: drag.current.angleDeg,
      })
      .subscribe({
        next: (region) => {
          this.replaceRegion(region);
          this.busy.set(false);
        },
        error: (error: unknown) => {
          this.error.set(httpError(error));
          this.busy.set(false);
          this.draw();
        },
      });
  }

  saveMetadata(): void {
    const scan = this.scan();
    const region = this.selected();
    const draft = this.draft();
    if (!scan || !region || !draft) {
      return;
    }
    const metadata = metadataFrom(draft);
    if (metadata === null) {
      this.error.set('Enter both latitude and longitude, or leave both empty.');
      return;
    }
    this.busy.set(true);
    this.api.patchRegion(scan.id, region.id, metadata).subscribe({
      next: (updated) => {
        this.replaceRegion(updated);
        this.notice.set('Photo details saved.');
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  addRegion(): void {
    const scan = this.scan();
    if (!scan) {
      return;
    }
    this.busy.set(true);
    this.api
      .createRegion(scan.id, {
        center_x: scan.width / 2,
        center_y: scan.height / 2,
        width: Math.max(8, scan.width * 0.28),
        height: Math.max(8, scan.height * 0.22),
        angle_deg: 0,
      })
      .subscribe({
        next: (region) => {
          this.scan.update((current) =>
            current
              ? {
                  ...current,
                  regions: [...current.regions, region],
                  region_count: current.region_count + 1,
                }
              : current,
          );
          this.selectedId.set(region.id);
          this.draft.set(draftFrom(region));
          this.dirty.set(false);
          this.busy.set(false);
        },
        error: (error: unknown) => {
          this.error.set(httpError(error));
          this.busy.set(false);
        },
      });
  }

  removeRegion(): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region || !window.confirm('Remove this photo from the scan?')) {
      return;
    }
    this.busy.set(true);
    this.api.deleteRegion(scan.id, region.id).subscribe({
      next: () => {
        this.scan.update((current) =>
          current
            ? {
                ...current,
                regions: current.regions.filter((item) => item.id !== region.id),
                region_count: Math.max(0, current.region_count - 1),
              }
            : current,
        );
        const next = this.scan()?.regions[0] ?? null;
        this.selectedId.set(next?.id ?? null);
        this.draft.set(next ? draftFrom(next) : null);
        this.dirty.set(false);
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  rotate(): void {
    const scan = this.scan();
    const region = this.selected();
    if (!scan || !region) {
      return;
    }
    this.busy.set(true);
    this.api.rotateRegion(scan.id, region.id).subscribe({
      next: (updated) => {
        this.replaceRegion(updated);
        this.notice.set('Rotated 90° clockwise. Upload again to send the new orientation.');
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  redetect(): void {
    const scan = this.scan();
    if (!scan) {
      return;
    }
    if (!window.confirm('Replace regions that have not been uploaded? Uploaded photos stay.')) {
      return;
    }
    this.busy.set(true);
    this.api.detect(scan.id).subscribe({
      next: (job) => {
        this.activeJob.set({ id: job.job_id, status: 'queued', error: null });
        this.notice.set('Detection queued.');
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  upload(regionId?: string): void {
    const scan = this.scan();
    if (!scan) {
      return;
    }
    this.busy.set(true);
    this.api.upload(scan.id, regionId ? [regionId] : undefined).subscribe({
      next: (job) => {
        this.activeJob.set({ id: job.job_id, status: 'queued', error: null });
        this.notice.set(regionId ? 'Upload queued for this photo.' : 'Upload queued.');
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  deleteScan(): void {
    const scan = this.scan();
    if (!scan || !window.confirm('Delete this scan, its regions, and the image files?')) {
      return;
    }
    this.api.deleteScan(scan.id).subscribe({
      next: () => void this.router.navigate(['/scans']),
      error: (error: unknown) => this.error.set(httpError(error)),
    });
  }

  private load(id: string): void {
    this.error.set('');
    this.api.getScan(id).subscribe({
      next: (scan) => this.applyScan(scan, true),
      error: (error: unknown) => this.error.set(httpError(error)),
    });
  }

  private reload(): void {
    const id = this.scanId();
    if (!id || this.drag()) {
      return;
    }
    this.api.getScan(id).subscribe({
      next: (scan) => this.applyScan(scan, false),
      error: () => undefined,
    });
  }

  private applyScan(scan: ScanDetail, resetNotice: boolean): void {
    this.scan.set(scan);
    if (resetNotice) {
      this.notice.set('');
    }
    const selected = scan.regions.find((region) => region.id === this.selectedId());
    if (selected && !this.dirty()) {
      this.draft.set(draftFrom(selected));
      return;
    }
    if (!selected) {
      const fallback = scan.regions[0] ?? null;
      this.selectedId.set(fallback?.id ?? null);
      this.draft.set(fallback ? draftFrom(fallback) : null);
      this.dirty.set(false);
    }
  }

  private replaceRegion(region: Region): void {
    this.scan.update((scan) =>
      scan
        ? { ...scan, regions: scan.regions.map((item) => (item.id === region.id ? region : item)) }
        : scan,
    );
    if (this.selectedId() === region.id) {
      this.draft.set(draftFrom(region));
      this.dirty.set(false);
    }
    this.error.set('');
  }

  private poll(): void {
    const job = this.activeJob();
    if (job && (job.status === 'queued' || job.status === 'running')) {
      this.api.getJob(job.id).subscribe({
        next: (next) => {
          this.activeJob.set({ id: next.id, status: next.status, error: next.error });
          if (next.status === 'finished' || next.status === 'failed') {
            if (next.error) {
              this.error.set(next.error);
            }
            this.reload();
          }
        },
        error: () => undefined,
      });
      return;
    }
    const scan = this.scan();
    if (
      scan &&
      scan.region_count === 0 &&
      !scan.detection_error &&
      !scan.files_deleted &&
      !this.dirty()
    ) {
      this.reload();
    }
  }

  private pointFrom(event: PointerEvent): { x: number; y: number } | null {
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
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }
    context.clearRect(0, 0, width, height);
    const scale = width / scan.width;
    const drag = this.drag();
    for (const region of scan.regions) {
      const rect = drag?.id === region.id ? drag.current : rectOf(region);
      drawRegion(context, region, rect, scale, region.id === this.selectedId());
    }
  }
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

function draftFrom(region: Region): Draft {
  return {
    takenAt: toDatetimeLocal(region.taken_at),
    description: region.description,
    albumId: region.album_id ?? '',
    latitude: region.latitude === null ? '' : String(region.latitude),
    longitude: region.longitude === null ? '' : String(region.longitude),
    favorite: region.is_favorite,
    rating: region.rating === null ? '' : String(region.rating),
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
  if ((lat !== null && Number.isNaN(lat)) || (lon !== null && Number.isNaN(lon))) {
    return null;
  }
  const visibility = draft.visibility;
  return {
    taken_at: fromDatetimeLocal(draft.takenAt),
    description: draft.description,
    album_id: draft.albumId || null,
    latitude: lat,
    longitude: lon,
    is_favorite: draft.favorite,
    rating: draft.rating ? Number(draft.rating) : null,
    visibility:
      visibility === 'timeline' || visibility === 'archive' || visibility === 'hidden'
        ? visibility
        : null,
  };
}

function pickRegion(
  regions: Region[],
  point: { x: number; y: number },
  scale: number,
  selectedId: string | null,
): { region: Region; hit: { kind: 'move' | 'resize' | 'rotate'; corner?: Corner } } | null {
  const selected = regions.find((region) => region.id === selectedId);
  if (selected) {
    const hit = hitTest(rectOf(selected), point, scale, true);
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

function drawRegion(
  context: CanvasRenderingContext2D,
  region: Region,
  rect: Rect,
  scale: number,
  selected: boolean,
): void {
  context.save();
  context.translate(rect.centerX * scale, rect.centerY * scale);
  context.rotate((rect.angleDeg * Math.PI) / 180);
  context.lineWidth = selected ? 2.5 : 1.5;
  context.strokeStyle = strokeColor(region);
  context.setLineDash(region.crop_changed ? [6, 4] : []);
  context.strokeRect(
    (-rect.width / 2) * scale,
    (-rect.height / 2) * scale,
    rect.width * scale,
    rect.height * scale,
  );
  if (selected) {
    const halfW = (rect.width / 2) * scale;
    const halfH = (rect.height / 2) * scale;
    context.beginPath();
    context.moveTo(0, -halfH);
    context.lineTo(0, -halfH - HANDLE_GAP_PX);
    context.stroke();
    fillHandle(context, 0, -halfH - HANDLE_GAP_PX);
    for (const [x, y] of [
      [-halfW, -halfH],
      [halfW, -halfH],
      [halfW, halfH],
      [-halfW, halfH],
    ]) {
      fillHandle(context, x, y);
    }
  }
  context.restore();
  context.fillStyle = strokeColor(region);
  context.font = '13px "Segoe UI", sans-serif';
  context.fillText(String(region.position), rect.centerX * scale + 6, rect.centerY * scale - 6);
}

function fillHandle(context: CanvasRenderingContext2D, x: number, y: number): void {
  context.fillStyle = '#fffdf8';
  context.strokeStyle = '#1c1915';
  context.setLineDash([]);
  context.beginPath();
  context.arc(x, y, 5, 0, Math.PI * 2);
  context.fill();
  context.stroke();
}

function strokeColor(region: Region): string {
  if (region.upload_status === 'failed') {
    return '#8d2f2f';
  }
  if (region.crop_changed) {
    return '#8a5a12';
  }
  if (region.upload_status === 'uploaded') {
    return '#0f6e56';
  }
  return '#1c1915';
}
