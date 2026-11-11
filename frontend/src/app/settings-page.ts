import { Component, DestroyRef, inject, signal } from '@angular/core';

import { ArchiveApi, httpError } from './api';
import { HelpTip } from './help-tip';
import { Album, ModelProgress, RetouchModel, ScannerDevice, Settings } from './models';

@Component({
  selector: 'app-settings-page',
  imports: [HelpTip],
  templateUrl: './settings-page.html',
})
export class SettingsPage {
  private readonly api = inject(ArchiveApi);

  readonly settings = signal<Settings | null>(null);
  readonly albums = signal<Album[]>([]);
  readonly albumsLoaded = signal(false);
  readonly devices = signal<ScannerDevice[]>([]);
  readonly scannerFound = signal<boolean | null>(null);
  readonly scannerMessage = signal('');
  readonly error = signal('');
  readonly notice = signal('');
  readonly connection = signal<{ ok: boolean; message: string } | null>(null);
  readonly busy = signal(false);
  readonly dirty = signal(false);
  readonly revealKey = signal(false);
  readonly resolutions = [150, 300, 600, 1200];
  readonly models = signal<RetouchModel[] | null>(null);
  readonly accepted = signal<Record<string, boolean>>({});
  readonly modelBusy = signal('');
  readonly modelError = signal<{ id: string; message: string } | null>(null);
  readonly modelNote = signal<{ id: string; message: string } | null>(null);
  private progressTimer: number | null = null;
  private modelsTicket = 0;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.stopWatching());
    this.api.getSettings().subscribe({
      next: (settings) => {
        this.settings.set(settings);
        this.loadAlbums();
      },
      error: (error: unknown) => this.error.set(httpError(error)),
    });
    this.loadModels();
    this.api.scannerStatus().subscribe({
      next: (status) => {
        this.devices.set(status.devices);
        this.scannerFound.set(status.scanner_found);
        this.scannerMessage.set(status.scanner_message);
      },
      error: () => this.scannerMessage.set(''),
    });
  }

  update<K extends keyof Settings>(key: K, value: Settings[K]): void {
    const current = this.settings();
    if (!current) {
      return;
    }
    this.settings.set({ ...current, [key]: value });
    this.dirty.set(true);
    this.notice.set('');
    if (key === 'immich_base_url' || key === 'immich_api_key') {
      this.connection.set(null);
    }
  }

  setDefaultAlbum(value: string): void {
    this.update('default_album_id', value.trim());
  }

  knownAlbum(id: string): boolean {
    return this.albums().some((album) => album.id === id);
  }

  knownDevice(name: string): boolean {
    return this.devices().some((device) => device.name === name);
  }

  setResolution(value: string): void {
    const dpi = Number(value);
    if (Number.isFinite(dpi) && dpi > 0) {
      this.update('resolution_dpi', dpi);
    }
  }

  setMillimetres(key: 'width_mm' | 'height_mm', value: string): void {
    if (!value.trim()) {
      this.update(key, null);
      return;
    }
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      this.update(key, parsed);
    }
  }

  setQuality(value: string): void {
    const quality = Number(value);
    if (Number.isFinite(quality)) {
      this.update('jpeg_quality', quality);
    }
  }

  setStep(
    key:
      | 'retouch_upscale'
      | 'retouch_denoise'
      | 'retouch_faces'
      | 'retouch_colorize'
      | 'retouch_scratches'
      | 'retouch_color_balance'
      | 'retouch_contrast'
      | 'retouch_dust'
      | 'retouch_deblur'
      | 'retouch_gentle_denoise'
      | 'retouch_paper_mesh'
      | 'retouch_paper_embossed',
    checked: boolean,
  ): void {
    this.update(key, checked);
  }

  setOutputScale(value: string): void {
    const scale = Number(value);
    if (scale !== 1 && scale !== 2 && scale !== 4) return;
    this.update('retouch_upscale', scale !== 1);
    this.update('retouch_output_scale', scale === 2 ? 2 : 4);
  }

  modelStatus(model: RetouchModel): string {
    if (!model.present) {
      return `${model.version} · not installed`;
    }
    if (model.matches_pin === false) {
      return `${model.version} · file does not match`;
    }
    if (model.matches_pin === true) {
      return `${model.version} · current`;
    }
    return `${model.version} · installed`;
  }

  fileSize(bytes: number | null): string {
    if (bytes == null) {
      return '';
    }
    if (bytes < 1024) {
      return `${bytes} B`;
    }
    if (bytes < 1024 * 1024) {
      return `${Math.round(bytes / 1024)} KB`;
    }
    if (bytes < 1024 * 1024 * 1024) {
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    }
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }

  modelInFlight(model: RetouchModel): boolean {
    return this.modelBusy() === model.id || model.progress !== null;
  }

  busyLabel(model: RetouchModel): string {
    if (model.progress?.phase === 'installing') {
      return 'Checking…';
    }
    if (model.can_update) {
      return 'Updating…';
    }
    if (model.can_redownload) {
      return 'Redownloading…';
    }
    return 'Downloading…';
  }

  progressPercent(progress: ModelProgress): number | null {
    if (progress.phase === 'installing') {
      return 100;
    }
    if (!progress.total) {
      return null;
    }
    return Math.min(100, Math.round((progress.received / progress.total) * 1000) / 10);
  }

  progressLabel(progress: ModelProgress): string {
    if (progress.phase === 'installing') {
      return 'Checking the file…';
    }
    if (!progress.total && progress.received === 0) {
      return 'Starting…';
    }
    const received = this.fileSize(progress.received);
    if (!progress.total) {
      return received;
    }
    const percent = Math.round(this.progressPercent(progress) ?? 0);
    return `${percent}% · ${received} of ${this.fileSize(progress.total)}`;
  }

  setAccepted(id: string, checked: boolean): void {
    this.accepted.update((current) => ({ ...current, [id]: checked }));
  }

  fetchModel(model: RetouchModel): void {
    this.modelBusy.set(model.id);
    this.modelError.set(null);
    this.modelNote.set(null);
    const note = model.can_update
      ? 'Updated.'
      : model.can_redownload
        ? 'Downloaded again.'
        : 'Downloaded.';
    this.models.update((items) =>
      (items ?? []).map((item) =>
        item.id === model.id
          ? {
              ...item,
              progress: item.progress ?? { received: 0, total: null, phase: 'downloading' },
            }
          : item,
      ),
    );
    this.watchDownloads();
    this.api.fetchRetouchModel(model.id, model.can_redownload).subscribe({
      next: (saved) => {
        this.modelsTicket += 1;
        this.models.update((items) =>
          (items ?? []).map((item) => (item.id === saved.id ? saved : item)),
        );
        this.modelNote.set({ id: saved.id, message: note });
        this.modelBusy.set('');
        this.syncWatch();
      },
      error: (error: unknown) => {
        this.modelsTicket += 1;
        this.modelError.set({ id: model.id, message: httpError(error) });
        this.models.update((items) =>
          (items ?? []).map((item) => (item.id === model.id ? { ...item, progress: null } : item)),
        );
        this.modelBusy.set('');
        this.syncWatch();
      },
    });
  }

  save(): void {
    const settings = this.settings();
    if (!settings) {
      return;
    }
    this.busy.set(true);
    this.error.set('');
    this.api.saveSettings(settings).subscribe({
      next: (saved) => {
        this.settings.set(saved);
        this.dirty.set(false);
        this.notice.set('Settings saved.');
        this.busy.set(false);
        this.loadAlbums();
      },
      error: (error: unknown) => {
        this.error.set(httpError(error));
        this.busy.set(false);
      },
    });
  }

  test(): void {
    const settings = this.settings();
    if (!settings) {
      return;
    }
    this.busy.set(true);
    this.connection.set(null);
    this.api.testConnection(settings).subscribe({
      next: (result) => {
        this.connection.set({
          ok: true,
          message: `Connected to Immich ${result.version} · ${result.album_count} albums`,
        });
        this.busy.set(false);
      },
      error: (error: unknown) => {
        this.connection.set({ ok: false, message: httpError(error) });
        this.busy.set(false);
      },
    });
  }

  private loadModels(): void {
    const ticket = ++this.modelsTicket;
    this.api.retouchModels().subscribe({
      next: (models) => {
        if (ticket !== this.modelsTicket) {
          return;
        }
        const busy = this.modelBusy();
        const previous = this.models();
        this.models.set(
          models.map((item) => {
            if (item.progress || busy !== item.id) {
              return item;
            }
            const held = previous?.find((model) => model.id === item.id)?.progress;
            return {
              ...item,
              progress: held ?? { received: 0, total: null, phase: 'downloading' },
            };
          }),
        );
        this.syncWatch();
      },
      error: (error: unknown) => {
        if (ticket !== this.modelsTicket || this.models() !== null) {
          return;
        }
        this.models.set([]);
        this.error.set(httpError(error));
      },
    });
  }

  private watchDownloads(): void {
    if (this.progressTimer !== null) {
      return;
    }
    this.progressTimer = window.setInterval(() => this.loadModels(), 400);
  }

  private stopWatching(): void {
    if (this.progressTimer === null) {
      return;
    }
    window.clearInterval(this.progressTimer);
    this.progressTimer = null;
  }

  private syncWatch(): void {
    const active = this.modelBusy() !== '' || (this.models() ?? []).some((model) => model.progress);
    if (active) {
      this.watchDownloads();
    } else {
      this.stopWatching();
    }
  }

  private loadAlbums(): void {
    this.api.listAlbums().subscribe({
      next: (albums) => {
        this.albums.set(albums);
        this.albumsLoaded.set(true);
      },
      error: () => {
        this.albums.set([]);
        this.albumsLoaded.set(true);
      },
    });
  }
}
