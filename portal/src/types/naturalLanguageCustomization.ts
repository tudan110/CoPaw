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

export interface NlCustomizationVersionRecord {
  versionId: string;
  title: string;
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
}

export interface NlCustomizationVersionListResponse {
  items: NlCustomizationVersionRecord[];
}
