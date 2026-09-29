export const ENVIRONMENT_TIERS = ["dev", "staging", "prod"] as const;
export type EnvironmentTier = (typeof ENVIRONMENT_TIERS)[number];

type GqlRef = { id: string; name: string };

export type BindingSinkType =
  "aws_secrets_manager" | "kubernetes_secret" | "none";

export interface BindingSinkConfig {
  type?: BindingSinkType;
  path_template?: string;
  integration_id?: string | null;
  region?: string | null;
  cluster_resource_id?: string | null;
  namespace?: string | null;
  secret_provider_class?: boolean;
  secret_provider_class_name?: string;
}

export interface GqlEnvironmentShort {
  id: string;
  name: string;
  displayName: string | null;
  tier: EnvironmentTier;
  region: string | null;
  status: string;
  entityName: string;
}

export interface GqlEnvironment extends GqlEnvironmentShort {
  description: string;
  rank: number;
  projectId: string | null;
  accountId: string | null;
  clusterName: string | null;
  workspaceId: string | null;
  storageId: string | null;
  storagePathPrefix: string | null;
  approvalRequired: boolean;
  bindingSink: BindingSinkConfig | null;
  labels: string[];
  revisionNumber: number;
  createdAt: string;
  updatedAt: string;
  project: GqlRef | null;
  workspace: GqlRef | null;
  storage: GqlRef | null;
  integrationIds: GqlRef[];
  parentResources: GqlRef[];
}

export interface EnvironmentCreateRequest {
  name: string;
  displayName: string | null;
  description: string;
  tier: EnvironmentTier;
  rank: number;
  projectId: string | null;
  region: string | null;
  accountId: string | null;
  clusterName: string | null;
  workspaceId: string | null;
  storageId: string | null;
  storagePathPrefix: string | null;
  integrationIds: string[];
  parentResources: string[];
  approvalRequired: boolean;
  bindingSink?: BindingSinkConfig | null;
  labels: string[];
}

export type EnvironmentUpdateRequest = Partial<
  Omit<EnvironmentCreateRequest, "name">
>;
