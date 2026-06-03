export interface AiBigScreenLayoutPosition {
  x?: number;
  y?: number;
  w?: number;
  h?: number;
}

export interface AiBigScreenComponent {
  id: string;
  type: "metric-card" | "line-chart" | "bar-chart" | "table" | "topology" | "text" | "group" | string;
  title: string;
  description?: string;
  layoutPosition?: AiBigScreenLayoutPosition;
  pluginId?: string;
  capabilityId?: string;
  queryParams?: Record<string, unknown>;
  visualConfig?: Record<string, unknown>;
  visualSpec?: Record<string, unknown>;
  refreshInterval?: number;
  interactions?: Record<string, unknown>;
  data?: Record<string, unknown>;
}

export interface AiBigScreenDataBinding {
  id: string;
  componentId: string;
  pluginId: string;
  input?: Record<string, unknown>;
  outputMapping?: Record<string, unknown>;
  refreshPolicy?: Record<string, unknown>;
  cachePolicy?: Record<string, unknown>;
  permissionScope?: string;
  sourceDescription?: string;
  skillName?: string;
}

export interface AiBigScreenFieldDefinition {
  key: string;
  label: string;
  aliases?: string[];
}

export interface AiBigScreenVersion {
  versionId: string;
  screenId: string;
  configSnapshot?: Record<string, unknown>;
  changeSummary?: string;
  changedBy?: string;
  changedByAi?: boolean;
  createdAt?: string;
  basedOnVersionId?: string;
}

export interface AiBigScreenPublishTarget {
  type: "portal-route" | "portal-menu" | "external-link" | "iframe" | "signed-link" | string;
  url: string;
  visibility?: string;
  expiresAt?: string | null;
  createdAt?: string;
  createdBy?: string;
}

export interface AiBigScreenApp {
  schemaVersion?: number;
  id: string;
  name: string;
  description?: string;
  owner?: string;
  status: "draft" | "published" | "archived" | string;
  layout: Record<string, unknown>;
  theme: Record<string, unknown>;
  components: AiBigScreenComponent[];
  dataBindings: AiBigScreenDataBinding[];
  permissions?: Record<string, unknown>;
  versions: AiBigScreenVersion[];
  publishTargets: AiBigScreenPublishTarget[];
  aiConversationContext?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
}

export interface AiBigScreenPlugin {
  id: string;
  name: string;
  domain: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
  outputSchema?: Record<string, unknown>;
  supportedVisuals?: string[];
  permissionScope?: string;
  cachePolicy?: Record<string, unknown>;
  refreshPolicy?: Record<string, unknown>;
  dataSource?: string;
  skillName?: string;
  availableFields?: AiBigScreenFieldDefinition[];
  sampleData?: Record<string, unknown>;
  examplePrompts?: string[];
}

export interface AiBigScreenResponse {
  screen: AiBigScreenApp;
}

export interface AiBigScreenListResponse {
  items: AiBigScreenApp[];
}

export interface AiBigScreenPluginsResponse {
  items: AiBigScreenPlugin[];
}

export interface AiBigScreenPatchResponse {
  screen: AiBigScreenApp;
  version: AiBigScreenVersion;
  summary: string;
}

export interface AiBigScreenPublishResponse {
  screen: AiBigScreenApp;
  publishTargets: AiBigScreenPublishTarget[];
}

export interface AiBigScreenDeleteResponse {
  screenId: string;
  deleted: boolean;
}
