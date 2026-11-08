import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { finalize } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import { MatchField, MatchingStatus, Photo, PhotoMatch, PhotoMatches } from './models';
import { displayedAspect, previewCacheKey } from './preview';
import { formatStamp } from './time';

@Component({
  selector: 'app-matching',
  imports: [FormsModule, RouterLink],
  templateUrl: './matching.html',
  styleUrl: './matching.css',
})
export class MatchingPage {
  private readonly api = inject(ArchiveApi);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private statusLoading = false;
  private statusRequest = 0;
  private loadedJob: string | null = null;
  private pairRequest = 0;

  readonly status = signal<MatchingStatus | null>(null);
  readonly results = signal<PhotoMatches | null>(null);
  readonly loading = signal(false);
  readonly starting = signal(false);
  readonly saving = signal('');
  readonly error = signal('');
  readonly statusError = signal('');
  readonly pairsError = signal('');
  readonly notice = signal('');
  readonly offset = signal(0);
  readonly pageSize = 10;
  readonly minimumScore = signal(0.82);
  readonly albums = signal<Record<string, string>>({});
  readonly formatStamp = formatStamp;
  readonly fields: MatchField[] = [
    'taken_at',
    'description',
    'album_id',
    'location',
    'is_favorite',
    'rating',
    'visibility',
  ];
  readonly labels: Record<MatchField, string> = {
    taken_at: 'Date taken',
    description: 'Description',
    album_id: 'Album',
    location: 'Location',
    is_favorite: 'Favorite',
    rating: 'Rating',
    visibility: 'Visibility',
  };
  readonly busy = computed(
    () => this.starting() || ['queued', 'running'].includes(this.status()?.job?.status ?? ''),
  );

  constructor() {
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const page = Number(params.get('page') ?? 1);
      const offset =
        Number.isSafeInteger(page) && page >= 1 && Number.isSafeInteger((page - 1) * this.pageSize)
          ? (page - 1) * this.pageSize
          : 0;
      if (offset === this.offset()) return;
      this.offset.set(offset);
      if (this.status() || this.results() || this.loading()) this.loadPairs();
    });
    this.refreshStatus();
    this.api
      .listAlbums()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (albums) => this.albums.set(Object.fromEntries(albums.map((a) => [a.id, a.name]))),
        // Matching works offline. Fall back to the stored album id.
        error: () => undefined,
      });
    const timer = window.setInterval(() => this.refreshStatus(), 2000);
    this.destroyRef.onDestroy(() => window.clearInterval(timer));
  }

  refreshStatus(afterStart = false): void {
    if (this.statusLoading && !afterStart) return;
    const request = ++this.statusRequest;
    this.statusLoading = true;
    this.api
      .matchingStatus()
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => {
          if (request !== this.statusRequest) return;
          this.statusLoading = false;
          if (afterStart) this.starting.set(false);
        }),
      )
      .subscribe({
        next: (status) => {
          if (request !== this.statusRequest) return;
          const previous = this.status();
          this.status.set(status);
          this.statusError.set('');
          if (!previous && status.progress) this.minimumScore.set(status.progress.minimum_score);
          const job = status.job;
          let reload = !previous;
          if (job?.status === 'finished' && this.loadedJob !== job.id) {
            this.loadedJob = job.id;
            if (previous) this.setOffset(0, true);
            reload = true;
          }
          if (reload) this.loadPairs();
        },
        error: (error: unknown) => {
          if (request !== this.statusRequest) return;
          this.statusError.set(httpError(error));
          if (!this.results() && !this.loading()) this.loadPairs();
        },
      });
  }

  run(): void {
    if (this.busy() || this.saving()) return;
    this.starting.set(true);
    this.error.set('');
    this.notice.set('');
    this.api
      .runMatching(Number(this.minimumScore()))
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: () => {
          // Keep the start button locked until the queued job is read back.
          this.refreshStatus(true);
        },
        error: (error: unknown) => {
          this.starting.set(false);
          this.error.set(httpError(error));
        },
      });
  }

  loadPairs(scrollToTop = false): void {
    const request = ++this.pairRequest;
    this.loading.set(true);
    this.api
      .matchingPairs(this.offset(), this.pageSize)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (results) => {
          if (request !== this.pairRequest) return;
          if (this.offset() > 0 && !results.items.length) {
            this.setOffset(
              Math.max(0, Math.ceil(results.total / this.pageSize) - 1) * this.pageSize,
              true,
            );
            this.loadPairs(scrollToTop);
            return;
          }
          this.results.set(results);
          this.pairsError.set('');
          this.loading.set(false);
          if (scrollToTop) window.scrollTo({ top: 0, behavior: 'auto' });
        },
        error: (error: unknown) => {
          if (request !== this.pairRequest) return;
          this.pairsError.set(httpError(error));
          this.loading.set(false);
        },
      });
  }

  page(direction: number): void {
    if (this.loading() || this.saving()) return;
    this.setOffset(Math.max(0, this.offset() + direction * this.pageSize));
    this.loadPairs(direction > 0);
  }

  private setOffset(offset: number, replaceUrl = false): void {
    this.offset.set(offset);
    void this.router.navigate([], {
      relativeTo: this.route,
      queryParams: { page: offset / this.pageSize + 1 },
      queryParamsHandling: 'merge',
      replaceUrl,
    });
  }

  key(pair: PhotoMatch): string {
    return `${pair.source.id}/${pair.target.id}`;
  }

  copy(pair: PhotoMatch, field: MatchField, replace = false): void {
    if (
      this.saving() ||
      this.loading() ||
      this.busy() ||
      (replace && !this.valuesDiffer(pair, field)) ||
      (!replace && !pair.fields.includes(field))
    )
      return;
    this.saving.set(`${this.key(pair)}/${field}`);
    this.error.set('');
    this.notice.set('');
    this.api
      .copyMatchField(pair, field, replace)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.saving.set('')),
      )
      .subscribe({
        next: () => {
          this.notice.set(
            `${this.labels[field]} ${replace ? 'replaced' : 'copied'}. Saved locally; upload the photo to sync with Immich.`,
          );
          this.loadPairs();
        },
        error: (error: unknown) => {
          this.error.set(httpError(error));
          this.loadPairs();
        },
      });
  }

  dismiss(pair: PhotoMatch, skip = false): void {
    if (this.saving() || this.loading() || this.busy()) return;
    this.saving.set(`${this.key(pair)}/${skip ? 'skip' : 'dismiss'}`);
    this.error.set('');
    this.notice.set('');
    this.api
      .dismissMatch(pair)
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.saving.set('')),
      )
      .subscribe({
        next: () => {
          if (skip)
            this.notice.set(
              'Suggestion skipped. No values were copied. It will stay hidden on future runs.',
            );
          this.loadPairs();
        },
        error: (error: unknown) => this.error.set(httpError(error)),
      });
  }

  previewUrl(photo: Photo): string {
    return this.api.regionPreviewUrl(photo.scan_id, photo.id, previewCacheKey(photo));
  }

  aspect(photo: Photo): number {
    return displayedAspect(photo.width, photo.height, photo.quarter_turns);
  }

  valuesDiffer(pair: PhotoMatch, field: MatchField): boolean {
    const { source, target } = pair;
    if (field === 'location') {
      return source.latitude !== target.latitude || source.longitude !== target.longitude;
    }
    if (field === 'taken_at' && source.taken_at && target.taken_at) {
      return Date.parse(source.taken_at) !== Date.parse(target.taken_at);
    }
    return source[field] !== target[field];
  }

  value(photo: Photo, field: MatchField): string {
    switch (field) {
      case 'taken_at':
        return photo.taken_at ? formatStamp(photo.taken_at) : '';
      case 'description':
        return photo.description?.trim() ?? '';
      case 'album_id':
        return photo.album_id ? (this.albums()[photo.album_id] ?? photo.album_id) : '';
      case 'location':
        return photo.latitude != null || photo.longitude != null
          ? `${photo.latitude ?? 'missing latitude'}, ${photo.longitude ?? 'missing longitude'}`
          : '';
      case 'is_favorite':
        return photo.is_favorite ? 'Yes' : '';
      case 'rating':
        return photo.rating != null ? `${photo.rating} / 5` : '';
      case 'visibility':
        return photo.visibility ?? '';
    }
  }

  score(pair: PhotoMatch): number {
    return Math.round(pair.score * 100);
  }
}
