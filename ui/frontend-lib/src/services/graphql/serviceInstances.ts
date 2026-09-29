import { ENVIRONMENT_SHORT_FIELDS } from "../../environments/graphql/fragments";
import { GqlEnvironmentShort } from "../../environments/types";

export interface GqlServiceInstance {
  id: string;
  state: string;
  status: string;
  createdAt: string;
  specRevisionApplied: number | null;
  workflowId: string | null;
  environment: GqlEnvironmentShort | null;
  resources: {
    id: string;
    alias: string;
    role: string;
    resource: { id: string; name: string } | null;
  }[];
}

export const SERVICE_INSTANCES_QUERY = `
  query ServiceInstances($filter: JSON, $sort: [String!], $range: [Int!]) {
    serviceInstances(filter: $filter, sort: $sort, range: $range) {
      id
      state
      status
      createdAt
      specRevisionApplied
      workflowId
      environment { ${ENVIRONMENT_SHORT_FIELDS} }
      resources { id alias role resource { id name } }
    }
  }
`;

export const SERVICE_INSTANCE_ACTIONS_QUERY = `
  query ServiceInstanceActions($id: UUID!) {
    serviceInstanceActions(id: $id)
  }
`;

export const CREATE_SERVICE_INSTANCE_MUTATION = `
  mutation CreateServiceInstance($input: ServiceInstanceCreateInput!) {
    createServiceInstance(input: $input) {
      id
    }
  }
`;

export const DELETE_SERVICE_INSTANCE_MUTATION = `
  mutation DeleteServiceInstance($id: UUID!) {
    deleteServiceInstance(id: $id)
  }
`;

export const SERVICE_INSTANCE_ACTION_MUTATION = `
  mutation ServiceInstanceAction($id: UUID!, $input: ServiceInstanceActionInput!) {
    serviceInstanceAction(id: $id, input: $input) {
      id
      state
      status
    }
  }
`;

export interface AdoptResourceInput {
  alias: string;
  resourceId: string;
  role: "dependency" | "workload" | "referenced";
}

export const ADOPT_RESOURCES_MUTATION = `
  mutation AdoptResources($input: AdoptResourcesInput!) {
    adoptResources(input: $input) {
      id
    }
  }
`;

export const RESOURCE_SEARCH_QUERY = `
  query ResourceSearch($filter: JSON, $range: [Int!]) {
    resources(filter: $filter, range: $range, sort: ["name", "ASC"]) {
      id
      name
      state
      template { template }
    }
  }
`;

export interface GqlMigrationResource {
  resourceId: string;
  name: string;
  template: string;
  state: string;
  alias: string;
  role: string;
  ownedBy: string | null;
}

export interface GqlMigrationProposal {
  anchorId: string;
  anchorName: string;
  projectId: string | null;
  serviceName: string;
  existingServiceId: string | null;
  environments: {
    environmentId: string;
    environmentName: string;
    resources: GqlMigrationResource[];
  }[];
  unmatched: GqlMigrationResource[];
  warnings: string[];
}

export const SERVICE_MIGRATION_ANCHORS_QUERY = `
  query ServiceMigrationAnchors($projectId: UUID) {
    serviceMigrationAnchors(projectId: $projectId) { id name }
  }
`;

const MIGRATION_RESOURCE_FIELDS = `resourceId name template state alias role ownedBy`;

export const SERVICE_MIGRATION_PREVIEW_QUERY = `
  query ServiceMigrationPreview($anchorResourceId: UUID!) {
    serviceMigrationPreview(anchorResourceId: $anchorResourceId) {
      anchorId
      anchorName
      projectId
      serviceName
      existingServiceId
      warnings
      unmatched { ${MIGRATION_RESOURCE_FIELDS} }
      environments {
        environmentId
        environmentName
        resources { ${MIGRATION_RESOURCE_FIELDS} }
      }
    }
  }
`;

export const APPLY_SERVICE_MIGRATION_MUTATION = `
  mutation ApplyServiceMigration($input: ApplyServiceMigrationInput!) {
    applyServiceMigration(input: $input) {
      id
      name
    }
  }
`;
