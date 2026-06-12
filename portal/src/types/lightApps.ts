export interface LightAppLaunch {
  type: "chat-dispatch" | "open-url";
  employeeId: string;
  prompt: string;
  url: string;
}

export interface LightAppRecord {
  kind: "page" | "task";
  id: string;
  appId: string;
  title: string;
  description: string;
  scenarioType: string;
  artifactType: string;
  tags: string[];
  listedAt: string;
  updatedAt: string;
  launch: LightAppLaunch;
}

export interface LightAppListResponse {
  items: LightAppRecord[];
}

export interface NlCustomizationClassifyResponse {
  recommendedKind: "page" | "task";
  scenarioType: string;
  triggerType: string;
  confidence: number;
}
