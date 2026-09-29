export interface GqlClaimableTemplate {
  id: string;
  name: string;
  template: string;
  description: string | null;
  parents: { id: string; name: string }[];
  configuration: { binding_outputs?: string[] } | null;
}

export interface GqlTemplateVersion {
  id: string;
  identifier: string;
  sourceCodeVersion: string | null;
  sourceCodeBranch: string | null;
  lifecycleState: string;
  status: string;
  index: number;
}

export interface GqlServicePlanItem {
  alias: string;
  action: "create" | "update" | "no_op" | "destroy";
  role: string;
  template: string | null;
  resourceId: string | null;
  resourceName: string | null;
  position: number | null;
  storagePath: string | null;
  parents: string[];
  wires: string[];
  changes: { field: string; before: any; after: any }[];
}

export interface GqlServicePlan {
  serviceInstanceId: string | null;
  items: GqlServicePlanItem[];
  errors: string[];
  creates: number;
  updates: number;
  noOps: number;
  destroys: number;
}

export interface GqlBindingItem {
  key: string;
  scope: string;
  value: string;
  sensitive: boolean;
  sources: string[];
}

export interface GqlServiceBindings {
  deployed: boolean;
  sink: string;
  path: string | null;
  namespace: string | null;
  secretProviderClass: string | null;
  manageSecretProviderClass: boolean;
  mountPath: string | null;
  runtime: GqlBindingItem[];
  build: GqlBindingItem[];
  errors: string[];
  appliedKeys: string[];
  appliedAt: string | null;
  appliedPath: string | null;
}

const BINDING_ITEM_FIELDS = "key scope value sensitive sources";

export const SERVICE_BINDINGS_QUERY = `
  query ServiceBindings($serviceId: UUID!, $environmentId: UUID!) {
    serviceBindings(serviceId: $serviceId, environmentId: $environmentId) {
      deployed
      sink
      path
      namespace
      secretProviderClass
      manageSecretProviderClass
      mountPath
      errors
      appliedKeys
      appliedAt
      appliedPath
      runtime { ${BINDING_ITEM_FIELDS} }
      build { ${BINDING_ITEM_FIELDS} }
    }
  }
`;

export const CLAIMABLE_TEMPLATES_QUERY = `
  query ClaimableTemplates {
    claimableTemplates {
      id
      name
      template
      description
      parents { id name }
      configuration
    }
  }
`;

export const TEMPLATE_VERSIONS_QUERY = `
  query TemplateVersions($filter: JSON, $sort: [String!], $range: [Int!]) {
    sourceCodeVersions(filter: $filter, sort: $sort, range: $range) {
      id
      identifier
      sourceCodeVersion
      sourceCodeBranch
      lifecycleState
      status
      index
    }
  }
`;

export const SERVICE_PLAN_QUERY = `
  query ServicePlan($serviceId: UUID!, $environmentId: UUID!) {
    servicePlan(serviceId: $serviceId, environmentId: $environmentId) {
      serviceInstanceId
      errors
      creates
      updates
      noOps
      destroys
      items {
        alias
        action
        role
        template
        resourceId
        resourceName
        position
        storagePath
        parents
        wires
        changes { field before after }
      }
    }
  }
`;
