export interface ClaimSpec {
  alias: string;
  template: string;
  source_code_version_id: string | null;
  variables: Record<string, any>;
  parents: string[];
  adopted?: boolean;
}

export interface BindingSpec {
  key: string;
  value: string;
  scope: "runtime" | "build";
}

export interface AppSpec {
  image: string;
  port: number;
  health_path: string | null;
  replicas: number;
  cpu: string;
  memory: string;
  env: Record<string, string>;
}

export interface WorkloadSpec {
  mode: "external" | "managed";
  app?: AppSpec | null;
  chart: string | null;
  chart_version: string | null;
  release_name: string | null;
  namespace: string | null;
  values_files: string[];
  values_ref: string;
  template: string;
  source_code_version_id: string | null;
  image_tag_key: string;
  atomic: boolean;
  wait: boolean;
  timeout: number;
  cleanup_on_fail: boolean;
}

export interface ServiceSpec {
  claims: ClaimSpec[];
  bindings?: BindingSpec[];
  workload?: WorkloadSpec | null;
}

export interface ServiceCreateRequest {
  name: string;
  displayName: string | null;
  description: string;
  projectId: string;
  repositoryUrl: string | null;
  labels: string[];
  owners: string[];
}

export interface ServiceUpdateRequest {
  name?: string;
  displayName?: string | null;
  description?: string;
  projectId?: string;
  repositoryUrl?: string | null;
  labels?: string[];
  owners?: string[];
  spec?: ServiceSpec;
}
