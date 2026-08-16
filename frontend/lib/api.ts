export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8100/api/v1";

export const TOKEN_STORAGE_KEY = "commerce-ai-access-token";

export type UserRole = "operator" | "designer" | "admin";

export type User = {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  roles: UserRole[];
  created_at: string;
};

export type Project = {
  id: string;
  created_by_id: string;
  name: string;
  platform: string;
  store_name: string;
  category: string | null;
  source: string;
  status: string;
  archived_at: string | null;
  deleted_by_id: string | null;
  deletion_reason: string | null;
  status_before_delete: string | null;
  created_at: string;
  updated_at: string;
};

export type ProductCard = {
  id: string;
  project_id: string;
  product_name: string;
  brand: string | null;
  current_title: string | null;
  facts: Record<string, unknown>;
  selling_points: Array<Record<string, unknown>>;
  specs: Array<Record<string, unknown>>;
  constraints: Record<string, unknown>;
  field_sources: Record<string, string>;
  missing_fields: Array<{
    field: string;
    label: string;
    impact: string;
    required_for: string[];
  }>;
  completeness_percent: number;
  revision: number;
  confirmed_by_id: string | null;
  confirmed_at: string | null;
};

export type Asset = {
  id: string;
  project_id: string;
  asset_type: string;
  source: string;
  storage_key: string | null;
  file_url: string | null;
  file_hash: string | null;
  mime_type: string | null;
  file_size: number | null;
  width: number | null;
  height: number | null;
  usage_note: string;
  selected_for_generation: boolean;
  is_archived: boolean;
  archive_blockers: string[];
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ContentVersion = {
  id: string;
  project_id: string;
  content_type: string;
  version_no: number;
  content: Record<string, unknown>;
  source_kind: string;
  created_by_id: string;
  status: string;
  is_final: boolean;
  finalized_by_id: string | null;
  finalized_at: string | null;
  created_at: string;
};

export type ProjectDetail = {
  project: Project;
  product_card: ProductCard | null;
  assets: Asset[];
  content_versions: ContentVersion[];
};

export type ProjectResult = {
  project: Project;
  product_card_confirmed: boolean;
  final_content: Record<string, Record<string, unknown>>;
  accepted_design_count: number;
  open_design_count: number;
  blockers: string[];
};

export type DesignSubmission = {
  id: string;
  task_id: string;
  submitted_by_id: string;
  version_no: number;
  file_url: string;
  notes: string;
  created_at: string;
};

export type DesignTask = {
  id: string;
  project_id: string;
  project_name: string;
  product_name: string | null;
  created_by_id: string;
  assigned_to_id: string;
  assigned_to_name: string;
  title: string;
  brief: string;
  requirements: Array<Record<string, unknown>>;
  priority: string;
  status: string;
  due_at: string | null;
  review_notes: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  submissions: DesignSubmission[];
};

export type SystemResource = {
  id: string;
  kind: string;
  name: string;
  description: string;
  content: Record<string, unknown>;
  version: number;
  is_active: boolean;
  updated_by_id: string;
  created_at: string;
  updated_at: string;
};

export type AuditEvent = {
  id: string;
  actor_id: string | null;
  project_id: string | null;
  action: string;
  object_type: string;
  object_id: string | null;
  request_id: string | null;
  payload_summary: Record<string, unknown>;
  result: string;
  created_at: string;
};

export type ImageWorkflow = {
  id: string;
  project_id: string;
  created_by_id: string;
  status: string;
  product_type: Record<string, unknown>;
  scene_plan: Record<string, unknown>;
  selected_scene: Record<string, unknown>;
  approved_prompt: string | null;
  qa_status: string;
  compliance_status: string;
  qa_report: Record<string, unknown>;
  compliance_report: Record<string, unknown>;
  confirmed_by_id: string | null;
  confirmed_at: string | null;
  revision: number;
  stale_reason: string | null;
  failure_code: string | null;
  created_at: string;
  updated_at: string;
};

export type ImageJob = {
  id: string;
  project_id: string;
  workflow_id: string;
  status: string;
  provider: string;
  model: string;
  prompt: string;
  error_code: string | null;
  error_message: string | null;
  outputs: Array<{
    id: string;
    sequence_no: number;
    mime_type: string | null;
    provider_url: string | null;
    b64_json: string | null;
    revised_prompt: string | null;
  }>;
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getStoredToken() {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token: string | null = getStoredToken(),
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    let message = `请求失败（${response.status}）`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        message = payload.detail;
      }
    } catch {
      // Keep the stable fallback when the server did not return JSON.
    }
    throw new ApiError(response.status, message);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function fileToDataUrl(file: File) {
  return await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("文件读取失败"));
    reader.readAsDataURL(file);
  });
}

export async function sha256File(file: File) {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export function jsonBody(value: unknown): RequestInit {
  return { body: JSON.stringify(value) };
}
