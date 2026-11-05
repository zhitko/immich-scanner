export interface Region {
  id: string;
  position: number;
  center_x: number;
  center_y: number;
  width: number;
  height: number;
  angle_deg: number;
  quarter_turns: number;
  taken_at: string | null;
  description: string;
  album_id: string | null;
  latitude: number | null;
  longitude: number | null;
  is_favorite: boolean;
  rating: number | null;
  visibility: string | null;
  upload_status: string;
  immich_asset_id: string | null;
  immich_status: string | null;
  album_linked: boolean;
  metadata_synced: boolean;
  upload_error: string | null;
  uploaded_at: string | null;
  crop_changed: boolean;
  needs_upload: boolean;
  retouch_upscale: boolean;
  retouch_faces: boolean;
  retouch_colorize: boolean;
  retouch_scratches: boolean;
  upload_source: 'crop' | 'retouch';
  retouch_status: string;
  retouch_error: string | null;
  retouch_signature: string | null;
  retouch_ready: boolean;
  retouch_version: string | null;
  retouch_reconstructs_faces: boolean;
  updated_at: string;
}

export interface ScanSummary {
  id: string;
  created_at: string;
  width: number;
  height: number;
  dpi: number | null;
  device_name: string | null;
  upload_state: string;
  files_deleted: boolean;
  detection_error: string | null;
  detecting: boolean;
  region_count: number;
  uploaded_count: number;
  original_filename: string;
}

export interface ScanDetail extends ScanSummary {
  regions: Region[];
}

export interface Job {
  id: string;
  type: string;
  status: string;
  scan_id: string | null;
  region_id: string | null;
  error: string | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Settings {
  immich_base_url: string;
  immich_api_key: string;
  output_format: 'jpeg' | 'png';
  jpeg_quality: number;
  default_album_id: string;
  device_name: string;
  resolution_dpi: number;
  scan_format: 'tiff' | 'png';
  scan_mode: 'Color' | 'Gray';
  width_mm: number | null;
  height_mm: number | null;
  retouch_upscale: boolean;
  retouch_faces: boolean;
  retouch_colorize: boolean;
  retouch_scratches: boolean;
}

export interface ScannerDevice {
  name: string;
  description: string;
}

export interface ScannerStatus {
  phase: 'idle' | 'scanning' | 'saving';
  phase_message: string;
  phase_started_at: string | null;
  scanner_found: boolean;
  scanner_message: string;
  devices: ScannerDevice[];
  last_scan_ok: boolean | null;
  last_scan_message: string;
  last_scan_id: string | null;
}

export interface ConnectionTest {
  ok: boolean;
  version: string;
  album_count: number;
}

export interface Album {
  id: string;
  name: string;
  asset_count: number;
}

export interface RegionGeometry {
  center_x: number;
  center_y: number;
  width: number;
  height: number;
  angle_deg: number;
}

export interface ModelProgress {
  received: number;
  total: number | null;
  phase: 'downloading' | 'installing';
}

export interface RetouchModel {
  id: string;
  purpose: string;
  version: string;
  license_id: string;
  license_summary: string;
  source_url: string;
  filename: string;
  present: boolean;
  matches_pin: boolean | null;
  automatic_download: boolean;
  can_download: boolean;
  can_update: boolean;
  can_redownload: boolean;
  size_bytes: number | null;
  progress: ModelProgress | null;
}

export interface RetouchChoice {
  upscale: boolean;
  faces: boolean;
  colorize: boolean;
  scratches: boolean;
}

export interface RetouchPatch {
  retouch_upscale?: boolean;
  retouch_faces?: boolean;
  retouch_colorize?: boolean;
  retouch_scratches?: boolean;
  upload_source?: 'crop' | 'retouch';
}

export interface RegionMetadata {
  taken_at: string | null;
  description: string;
  album_id: string | null;
  latitude: number | null;
  longitude: number | null;
  is_favorite: boolean;
  rating: number | null;
  visibility: string | null;
}
