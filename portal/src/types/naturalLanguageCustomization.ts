export interface NlCustomizationIntent {
  scenarioType: string;
  targetType: string;
  targetName: string;
  triggerType: string;
  triggerLabel: string;
  scheduleCron: string;
  actions: string[];
  displayTargets: string[];
  roles: string[];
  restrictions: string[];
  approvalMode: string;
  confidence: number;
}

export interface NlCustomizationMatchedTemplate {
  templateId: string;
  templateName: string;
  templateKind: string;
  skillId: string;
  confidence: number;
  reasons: string[];
}

export interface NlCustomizationPreviewResponse {
  previewId: string;
  appId?: string;
  title: string;
  prompt: string;
  intent: NlCustomizationIntent;
  matchedTemplate: NlCustomizationMatchedTemplate;
  bundle: Record<string, unknown>;
  summaryMarkdown: string;
  warnings: string[];
  missingInputs: string[];
}

export interface NlCustomizationPublishResponse {
  versionId: string;
  publishedAt: string;
  bundlePath: string;
  record: NlCustomizationVersionRecord;
}

export interface NlCustomizationApplyResponse {
  versionId: string;
  appliedAt: string;
  activePath: string;
  record: NlCustomizationVersionRecord;
}

export interface NlCustomizationVersionRecord {
  appId?: string;
  versionId: string;
  title: string;
  description?: string;
  prompt: string;
  scenarioType: string;
  targetType: string;
  matchedTemplateId: string;
  matchedSkillId: string;
  requestedBy: string;
  publishedAt: string;
  warningCount: number;
  bundlePath: string;
  summaryMarkdown: string;
  isActive?: boolean;
  isListed?: boolean;
  listedAt?: string;
  isInstalled?: boolean;
  appliedAt?: string;
  activePath?: string;
}

export interface NlCustomizationVersionListResponse {
  items: NlCustomizationVersionRecord[];
}

export interface NlCustomizationVersionDetailResponse {
  versionId: string;
  record: NlCustomizationVersionRecord;
  preview: NlCustomizationPreviewResponse;
  bundlePath: string;
}

export interface NlCustomizationDeleteResponse {
  versionId: string;
  deleted: boolean;
  bundlePath: string;
  record: NlCustomizationVersionRecord;
}

export interface NlCustomizationActiveResponse {
  activeVersionId: string;
  appliedAt: string;
  activePath: string;
  record: NlCustomizationVersionRecord | null;
  preview?: NlCustomizationPreviewResponse | null;
  effectiveBundle: Record<string, unknown>;
}

export interface NlCustomizationAppRecord {
  appId: string;
  versionId: string;
  title: string;
  description: string;
  prompt: string;
  scenarioType: string;
  targetType: string;
  matchedSkillId: string;
  displayTargets: string[];
  launchEmployeeId: string;
  launchPrompt: string;
  listedAt: string;
  installedAt: string;
  publishedAt: string;
  isListed?: boolean;
  isInstalled?: boolean;
  isActive?: boolean;
}

export interface NlCustomizationAppListResponse {
  items: NlCustomizationAppRecord[];
}
