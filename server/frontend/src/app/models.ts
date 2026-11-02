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
