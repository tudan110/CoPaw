export interface ResourceImportCiTypeAttributeDefinition {
  id?: number | string;
  name: string;
  alias?: string;
  required?: boolean;
  is_choice?: boolean;
  is_list?: boolean;
  default_show?: boolean;
  default?: unknown;
  value_type?: string;
  choices?: Array<{
    value: string;
    label?: string;
  }>;
}

export interface ResourceImportCiTypeMetadata {
  id?: number | string;
  name: string;
  alias?: string;
  unique_key?: string;
  system_generated_unique_key?: boolean;
  attributes?: string[];
  attributeDefinitions?: ResourceImportCiTypeAttributeDefinition[];
  parentTypes?: Array<{
    name: string;
    alias?: string;
    relationType?: string;
    showKey?: string;
  }>;
}

export interface ResourceImportCiTypeGroup {
  id?: number | string;
  name: string;
  ciTypes: Array<{
    id?: number | string;
    name: string;
    alias?: string;
  }>;
}

export interface ResourceImportMetadata {
  supportedFormats: string[];
  ciTypes: ResourceImportCiTypeMetadata[];
  ciTypeGroups?: ResourceImportCiTypeGroup[];
  relationTypes: string[];
  connected: boolean;
  message: string;
}

export interface ResourceImportStartBlock {
  title: string;
  ordered?: boolean;
  items?: string[];
  paragraphs?: string[];
}

export interface ResourceImportStartPayload {
  copyBlocks: ResourceImportStartBlock[];
  supportedFormats: string[];
  startPrompt?: string;
  topologyPrompt?: string;
}

export interface ResourceImportRecord {
  previewKey: string;
  ciType: string;
  name: string;
  category: string;
  generated: boolean;
  selected: boolean;
  importAction?: "create" | "update" | "skip";
  existingCi?: {
    ciId?: string | number;
    matchField?: string;
    matchValue?: string;
    name?: string;
    status?: string;
  } | null;
  issues?: Array<{
    field: string;
    level: string;
    message: string;
  }>;
  attentionFields?: string[];
  attributes: Record<string, string>;
  sourceRows: Array<{
    filename?: string;
    sheet?: string;
    rowIndex?: number;
  }>;
  sourceAttributes?: Record<string, string>;
  analysisAttributes?: Record<string, string>;
  autoFilledHints?: string[];
}

export interface ResourceImportGroup {
  ciType: string;
  label: string;
  count: number;
  records: ResourceImportRecord[];
}

export interface ResourceImportRelation {
  sourceKey: string;
  targetKey: string;
  relationType: string;
  confidence: string;
  reason: string;
  selected: boolean;
  requiresModelRelation?: boolean;
  sourceType?: string;
  targetType?: string;
  sourceName?: string;
  targetName?: string;
}

export interface ResourceImportPreview {
  summary: {
    fileCount: number;
    rawRowCount: number;
    resourceCount: number;
    relationCount: number;
    qualityScore: number;
    autoCleaned: number;
    needsConfirmation: number;
    analysisIssueCount?: number;
    blockingIssueCount?: number;
  };
  mappingSummary: Array<{
    fileName?: string;
    sheetName?: string;
    sourceField: string;
    targetField: string;
    suggestedTargetField?: string;
    count: number;
    confidence: string;
    status?: "mapped" | "unmapped" | "needs_confirmation";
    resolvedBy?: string;
    message?: string;
    needsConfirmation?: boolean;
    candidates?: Array<{
      targetField: string;
      confidence: string;
      source?: string;
    }>;
  }>;
  cleaningSummary: Array<{
    label: string;
    count: number;
  }>;
  ciTypeMetadata?: Record<string, ResourceImportCiTypeMetadata>;
  structureAnalysis?: {
    items: Array<{
      key: string;
      resourceCiType: string;
      resourceLabel: string;
      recordCount: number;
      status:
        | "matched"
        | "ambiguous_model"
        | "missing_group"
        | "missing_model"
        | "unknown";
      reason?: string;
      originalTypeText?: string;
      rawTypeHints?: string[];
      semanticConfidence?: "high" | "medium" | "low";
      suggestedGroupName?: string;
      suggestedModelName?: string;
      selectedGroupName?: string;
      selectedModelName?: string;
      createGroupApproved?: boolean;
      createModelApproved?: boolean;
      needsConfirmation?: boolean;
      groupOptions?: Array<{
        id?: number | string;
        name: string;
        existing: boolean;
      }>;
      modelOptions?: Array<{
        id?: number | string;
        name: string;
        alias?: string;
        groupName?: string;
        existing: boolean;
      }>;
      modelDraft?: {
        name?: string;
        alias?: string;
        inheritFrom?: string;
        uniqueKey?: string;
      };
    }>;
  };
  importSummary?: {
    createCount: number;
    updateCount: number;
    skipCount: number;
    pendingGroups: Array<{ name: string; ciTypes: string[] }>;
    pendingModels: Array<{ name: string; group: string }>;
    attentionRecords: Array<{
      previewKey: string;
      name: string;
      ciType: string;
      issues: Array<{ field: string; level: string; message: string }>;
    }>;
    blockingCount: number;
  };
  analysisStatus?: "ok" | "blocking";
  analysisIssues?: Array<{
    kind: string;
    severity: "warning" | "blocking";
    message: string;
    fileName?: string;
    sheetName?: string;
  }>;
  metadataConnected?: boolean;
  metadataMessage?: string;
  resourceGroups: ResourceImportGroup[];
  relations: ResourceImportRelation[];
  logs: string[];
  warnings: string[];
}

export interface ResourceImportPreviewJobEvent {
  timestamp?: string;
  stage?: string;
  message?: string;
  percent?: number;
}

export interface ResourceImportPreviewJob {
  jobId: string;
  status: "queued" | "running" | "completed" | "failed";
  createdAt?: string;
  updatedAt?: string;
  progressStage?: string;
  progressMessage?: string;
  progressPercent?: number;
  progressEvents?: ResourceImportPreviewJobEvent[];
  logs?: string[];
  preview?: ResourceImportPreview | null;
  error?: string;
}

export interface ResourceImportResult {
  status: string;
  created: number;
  relationsCreated: number;
  skipped: number;
  failed: number;
  error?: string;
  structureResults?: Array<{
    kind: string;
    status?: string;
    message: string;
    name?: string;
    groupName?: string;
    modelName?: string;
    sourceType?: string;
    targetType?: string;
    relationType?: string;
    ctrId?: string | number;
  }>;
  resourceResults?: Array<{
    previewKey: string;
    ciId?: string | number;
    status: string;
    message: string;
  }>;
  relationResults?: Array<{
    sourceKey: string;
    targetKey: string;
    status: string;
    message: string;
  }>;
}
