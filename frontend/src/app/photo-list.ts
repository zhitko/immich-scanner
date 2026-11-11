import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { ArchiveApi, httpError } from './api';
import { Photo, PhotoFilter } from './models';
import { chosenVersion, displayedAspect, previewCacheKey } from './preview';
import { formatStamp } from './time';

@Component({
  selector: 'app-photo-list',
  imports: [RouterLink],
  templateUrl: './photo-list.html',
})
export class PhotoListPage {
  private readonly api = inject(ArchiveApi);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private loadId = 0;

  readonly statuses = [
    { value: 'open', label: 'Waiting' },
    { value: 'uploaded', label: 'Uploaded' },
    { value: 'all', label: 'All' },
  ] as const;
  readonly filters: { value: PhotoFilter; label: string }[] = [
    { value: 'original', label: 'Original' },
    { value: 'retouched', label: 'Retouched' },
    { value: 'has-date', label: 'Has date' },
    { value: 'no-date', label: 'Has no date' },
  ];
  readonly mode = signal<'open' | 'uploaded' | 'all'>('open');
  readonly selectedFilters = signal<PhotoFilter[]>([]);
  readonly photos = signal<Photo[] | null>(null);
  readonly error = signal('');
  readonly formatStamp = formatStamp;

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed()).subscribe((params) => {
      const status = params.get('status');
      this.mode.set(status === 'uploaded' || status === 'all' ? status : 'open');
      this.selectedFilters.set(
        this.filters
          .map((filter) => filter.value)
          .filter((value) => params.getAll('filter').includes(value)),
      );
      this.load();
    });
    const timer = window.setInterval(() => {
      if (
        this.photos()?.some(
          (photo) =>
            photo.upload_status === 'uploading' ||
            photo.retouch_status === 'queued' ||
            photo.retouch_status === 'running',
        )
      ) {
        this.load(true);
      }
    }, 2000);
    inject(DestroyRef).onDestroy(() => window.clearInterval(timer));
  }

  choose(mode: 'open' | 'uploaded' | 'all'): void {
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { status: mode === 'open' ? null : mode },
      queryParamsHandling: 'merge',
    });
  }

  toggleFilter(filter: PhotoFilter): void {
    const selected = this.selectedFilters();
    const filters = selected.includes(filter)
      ? selected.filter((value) => value !== filter)
      : [...selected, filter];
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { filter: filters.length ? filters : null },
      queryParamsHandling: 'merge',
    });
  }

  previewUrl(photo: Photo): string {
    return chosenVersion(photo) === 'retouch'
      ? this.api.retouchPreviewUrl(photo.scan_id, photo.id, photo.retouch_version ?? '')
      : this.api.regionPreviewUrl(photo.scan_id, photo.id, previewCacheKey(photo));
  }

  previewTurns(photo: Photo): number {
    return chosenVersion(photo) === 'retouch' ? 0 : photo.quarter_turns % 4;
  }

  aspect(photo: Photo): number {
    return displayedAspect(photo.width, photo.height, photo.quarter_turns);
  }

  private load(quiet = false): void {
    const loadId = ++this.loadId;
    if (!quiet) {
      this.photos.set(null);
      this.error.set('');
    }
    this.api.listPhotos(this.mode(), this.selectedFilters()).subscribe({
      next: (photos) => {
        if (loadId === this.loadId) this.photos.set(photos);
      },
      error: (error: unknown) => {
        if (loadId === this.loadId && !quiet) {
          this.photos.set([]);
          this.error.set(httpError(error));
        }
      },
    });
  }
}
