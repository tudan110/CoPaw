import { requestPortalApi } from "./portalWorkorders";

const KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS = 60000;

export type KnowledgeBaseHealth = {
  status?: string;
  storage?: {
    skillRoot?: string;
    dataDir?: string;
    dbPath?: string;
  };
  llm?: {
    enabled?: boolean;
    provider?: string;
  };
  embedding?: {
    enabled?: boolean;
    key_configured?: boolean;
    env_forced_off?: boolean;
    provider?: string;
  };
};

export type KnowledgeEvidence = {
  evidence_id: string;
  confidence_score?: number;
  confidence_level?: string;
  chunk_summary?: string;
  chunk_text?: string;
  source_time?: string;
  source_type?: string;
  citation?: {
    source_label?: string;
    source_scope_label?: string;
    source_time?: string;
    locator?: string;
  };
  meta?: Record<string, unknown>;
};

export type KnowledgeUnit = {
  id: string;
  title?: string;
  content?: string;
  locator?: string;
  source_type?: string;
  source_scope?: string;
  created_at?: string;
  meta?: Record<string, unknown>;
};

export type KnowledgeQueryResponse = {
  query_id?: string;
  summary?: string;
  relevant_evidence?: KnowledgeEvidence[];
  evidence_boundary_statement?: string;
  flags?: {
    insufficient_evidence?: boolean;
  };
};

export type KnowledgeSourceRecord = {
  id: number;
  filename: string;
  source_type?: string;
  source_scope?: string;
  builtin_pack_id?: string;
  builtin_pack_version?: string;
  uploaded_at?: string;
  note?: string;
  archived_at?: string | null;
  archive_reason?: string | null;
  unit_count?: number;
  meta?: {
    display_title?: string;
    tags?: string[];
    scope_label?: string;
  };
};

export type KnowledgeSourceDetail = KnowledgeSourceRecord & {
  units?: KnowledgeUnit[];
  storage_path?: string;
};

export type KnowledgeSourceListResponse = {
  items: KnowledgeSourceRecord[];
  total?: number;
  limit?: number;
  offset?: number;
};

export type KnowledgeIngestJob = {
  job_id?: string;
  id?: string;
  filename?: string;
  source_type?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
  finished_at?: string;
  progress_pct?: number;
  current_stage?: string;
  unit_count?: number;
  note?: string;
  poll_url?: string;
  document_id?: number | null;
  document_deleted?: boolean;
};

export type KnowledgeIngestJobListResponse = {
  items: KnowledgeIngestJob[];
};

export type KnowledgeBuiltinPack = {
  pack_id: string;
  version?: string;
  title?: string;
  description?: string;
  scope_label?: string;
  enabled?: boolean;
  manifest_path?: string;
  declared_file_count?: number;
  imported_source_count?: number;
  imported_unit_count?: number;
  imported_at?: string;
};

export type KnowledgeBuiltinPackListResponse = {
  items: KnowledgeBuiltinPack[];
};

export type KnowledgeSourceSummaryItem = {
  source_scope?: string;
  source_type?: string;
  builtin_pack_id?: string;
  unit_count?: number;
  source_count?: number;
  latest_created_at?: string;
};

export type KnowledgeSourceSummaryResponse = {
  items: KnowledgeSourceSummaryItem[];
};

export type KnowledgeUnitListResponse = {
  items: Array<KnowledgeUnit & {
    filename?: string;
    uploaded_at?: string;
    builtin_pack_id?: string;
    builtin_pack_version?: string;
  }>;
};

export type KnowledgeRagResponse = {
  answer?: string;
  provider?: string;
  provider_name?: string;
  model?: string;
  model_name?: string;
  model_label?: string;
  model_source?: string;
  evidence_ids?: string[];
  latency_ms?: number;
  skipped?: boolean;
  reason?: string;
};

export function getKnowledgeBaseHealth() {
  return requestPortalApi<KnowledgeBaseHealth>(
    "/knowledge-base/health",
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function queryKnowledgeBase(
  query: string,
  filters: Record<string, unknown> = {},
  signal?: AbortSignal,
) {
  return requestPortalApi<KnowledgeQueryResponse>(
    "/knowledge-base/query",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, filters }),
      signal,
    },
    60000,
  );
}

export function synthesizeKnowledgeAnswer(
  query: string,
  evidenceIds: string[],
  agentId = "knowledge",
  signal?: AbortSignal,
) {
  return requestPortalApi<KnowledgeRagResponse>(
    "/knowledge-base/rag-synthesize",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Agent-Id": agentId,
      },
      body: JSON.stringify({ query, evidence_ids: evidenceIds }),
      signal,
    },
    90000,
  );
}

export function listKnowledgeSources(params: {
  limit?: number;
  offset?: number;
  includeArchived?: boolean;
  filename?: string;
  sourceScope?: string;
  sourceType?: string;
  builtinPackId?: string;
} = {}) {
  const search = new URLSearchParams();
  search.set("limit", String(params.limit || 50));
  search.set("offset", String(params.offset || 0));
  search.set("include_archived", String(Boolean(params.includeArchived)));
  if (params.filename) {
    search.set("filename", params.filename);
  }
  if (params.sourceScope) {
    search.set("source_scope", params.sourceScope);
  }
  if (params.sourceType) {
    search.set("source_type", params.sourceType);
  }
  if (params.builtinPackId) {
    search.set("builtin_pack_id", params.builtinPackId);
  }
  return requestPortalApi<KnowledgeSourceListResponse>(
    `/knowledge-base/sources?${search}`,
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function getKnowledgeSourceDetail(sourceRecordId: number, includeArchived = false) {
  const search = new URLSearchParams();
  search.set("include_archived", String(includeArchived));
  return requestPortalApi<KnowledgeSourceDetail>(
    `/knowledge-base/sources/${encodeURIComponent(String(sourceRecordId))}?${search}`,
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function uploadKnowledgeFile(file: File) {
  const formData = new FormData();
  formData.append("file", file, file.name);
  return requestPortalApi<KnowledgeIngestJob>(
    "/knowledge-base/ingest",
    {
      method: "POST",
      body: formData,
    },
    120000,
  );
}

export function getKnowledgeIngestProgress(jobId: string) {
  return requestPortalApi<KnowledgeIngestJob>(
    `/knowledge-base/ingestion-jobs/${encodeURIComponent(jobId)}/progress`,
    {},
    60000,
  );
}

export function listKnowledgeIngestJobs(limit = 20) {
  return requestPortalApi<KnowledgeIngestJobListResponse>(
    `/knowledge-base/ingestion-jobs?limit=${encodeURIComponent(String(limit))}`,
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function createKnowledgeManualEntry(payload: {
  title: string;
  content: string;
  tags?: string[];
}) {
  return requestPortalApi<Record<string, unknown>>(
    "/knowledge-base/manual-entry",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function archiveKnowledgeSources(sourceRecordIds: number[], reason = "portal archive") {
  return requestPortalApi<Record<string, unknown>>(
    "/knowledge-base/sources/archive",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_record_ids: sourceRecordIds, reason }),
    },
  );
}

export function updateKnowledgeSource(payload: {
  sourceRecordId: number;
  displayTitle?: string;
  tags?: string[];
  note?: string;
  sourceScope?: string;
}) {
  return requestPortalApi<Record<string, unknown>>(
    "/knowledge-base/sources/update",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source_record_id: payload.sourceRecordId,
        display_title: payload.displayTitle || "",
        tags: payload.tags || [],
        note: payload.note || "",
        source_scope: payload.sourceScope || "",
      }),
    },
  );
}

export function unarchiveKnowledgeSources(sourceRecordIds: number[]) {
  return requestPortalApi<Record<string, unknown>>(
    "/knowledge-base/sources/unarchive",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_record_ids: sourceRecordIds }),
    },
  );
}

export function deleteKnowledgeSources(sourceRecordIds: number[], reason = "portal delete") {
  return requestPortalApi<Record<string, unknown>>(
    "/knowledge-base/sources/delete",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_record_ids: sourceRecordIds, reason }),
    },
  );
}

export function toggleKnowledgeEmbedding(enabled: boolean) {
  return requestPortalApi<KnowledgeBaseHealth["embedding"] & { changed?: boolean; reject_reason?: string | null }>(
    "/knowledge-base/embedding/toggle",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    },
  );
}

export function reindexKnowledgeEmbeddings(force = false) {
  return requestPortalApi<Record<string, unknown>>(
    `/knowledge-base/embeddings/reindex?force=${String(force)}`,
    { method: "POST" },
    120000,
  );
}

export function getKnowledgeSourceSummary() {
  return requestPortalApi<KnowledgeSourceSummaryResponse>(
    "/knowledge-base/source-summary",
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function listKnowledgeUnits(params: {
  limit?: number;
  includeArchived?: boolean;
  filename?: string;
  sourceScope?: string;
  sourceType?: string;
  builtinPackId?: string;
} = {}) {
  const search = new URLSearchParams();
  search.set("limit", String(params.limit || 50));
  search.set("include_archived", String(Boolean(params.includeArchived)));
  if (params.filename) {
    search.set("filename", params.filename);
  }
  if (params.sourceScope) {
    search.set("source_scope", params.sourceScope);
  }
  if (params.sourceType) {
    search.set("source_type", params.sourceType);
  }
  if (params.builtinPackId) {
    search.set("builtin_pack_id", params.builtinPackId);
  }
  return requestPortalApi<KnowledgeUnitListResponse>(
    `/knowledge-base/units?${search}`,
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function listKnowledgeBuiltinPacks() {
  return requestPortalApi<KnowledgeBuiltinPackListResponse>(
    "/knowledge-base/builtin-packs",
    {},
    KNOWLEDGE_BASE_MANAGEMENT_TIMEOUT_MS,
  );
}

export function reloadKnowledgeBuiltinPacks(params: {
  force?: boolean;
  packId?: string;
} = {}) {
  return requestPortalApi<Record<string, unknown>>(
    "/knowledge-base/builtin-packs/reload",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        force: params.force ?? true,
        pack_id: params.packId || undefined,
      }),
    },
    120000,
  );
}
