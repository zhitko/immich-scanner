import { DecimalPipe } from '@angular/common';
import { Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { finalize } from 'rxjs';

import { ArchiveApi, httpError } from './api';
import { Statistics } from './models';
import { formatStamp } from './time';

@Component({
  selector: 'app-statistics',
  imports: [DecimalPipe],
  templateUrl: './statistics.html',
  styleUrl: './statistics.css',
})
export class StatisticsPage {
  private readonly api = inject(ArchiveApi);
  private readonly destroyRef = inject(DestroyRef);

  readonly statistics = signal<Statistics | null>(null);
  readonly loading = signal(false);
  readonly error = signal('');
  readonly metadata = [
    { key: 'with_date', label: 'Date taken' },
    { key: 'with_description', label: 'Description' },
    { key: 'with_album', label: 'Album assigned' },
    { key: 'with_location', label: 'Location' },
    { key: 'with_rating', label: 'Rating' },
    { key: 'favorites', label: 'Favorites' },
  ] as const;
  readonly uploads = [
    { key: 'uploaded', label: 'Uploaded' },
    { key: 'pending', label: 'Pending' },
    { key: 'uploading', label: 'Uploading' },
    { key: 'failed', label: 'Failed' },
  ] as const;
  readonly dates = [
    { key: 'first_scan_at', label: 'First scan' },
    { key: 'latest_scan_at', label: 'Latest scan' },
    { key: 'earliest_photo_at', label: 'Earliest photo date' },
    { key: 'latest_photo_at', label: 'Latest photo date' },
    { key: 'latest_upload_at', label: 'Latest upload' },
  ] as const;
  readonly retouchSteps = [
    { key: 'retouched_scratches', label: 'Fill scratches' },
    { key: 'retouched_color_balance', label: 'Correct color cast' },
    { key: 'retouched_contrast', label: 'Restore contrast' },
    { key: 'retouched_dust', label: 'Dust removal' },
    { key: 'retouched_deblur', label: 'Deblur' },
    { key: 'retouched_gentle_denoise', label: 'Gentle denoise' },
    { key: 'retouched_paper_mesh', label: 'Repeating paper texture reduction' },
    { key: 'retouched_paper_embossed', label: 'Embossed paper texture reduction' },
    { key: 'retouched_light_corners', label: 'Light corner repair' },
    { key: 'retouched_colorize', label: 'Colorize' },
    { key: 'retouched_upscale', label: 'Upscale' },
    { key: 'retouched_denoise', label: 'Denoise' },
    { key: 'retouched_faces', label: 'Restore faces' },
  ] as const;
  readonly formatStamp = formatStamp;

  constructor() {
    this.load();
  }

  percentage(count: number, total: number): number {
    return total ? Math.round((count / total) * 100) : 0;
  }

  load(): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.error.set('');
    this.api
      .getStatistics()
      .pipe(
        takeUntilDestroyed(this.destroyRef),
        finalize(() => this.loading.set(false)),
      )
      .subscribe({
        next: (statistics) => this.statistics.set(statistics),
        error: (error: unknown) => this.error.set(httpError(error)),
      });
  }
}
