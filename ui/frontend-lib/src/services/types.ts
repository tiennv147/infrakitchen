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

export interface ServiceSpec {
  claims: ClaimSpec[];
  bindings?: BindingSpec[];
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
