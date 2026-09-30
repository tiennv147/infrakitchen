export interface GqlServiceDeployment {
  id: string;
  serviceInstanceId: string;
  environmentId: string;
  environmentName: string;
  batchId: string;
  position: number;
  version: string;
  previousVersion: string | null;
  status: "waiting" | "active" | "done" | "error" | "cancelled" | "superseded";
  source: string;
  message: string | null;
  createdByName: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}

export interface GqlDeployToken {
  id: string;
  name: string;
  token: string;
  tokenPrefix: string;
  expiresAt: string | null;
}

const DEPLOYMENT_FIELDS = `
  id
  serviceInstanceId
  environmentId
  environmentName
  batchId
  position
  version
  previousVersion
  status
  source
  message
  createdByName
  createdAt
  startedAt
  finishedAt
`;

export const SERVICE_DEPLOYMENTS_QUERY = `
  query ServiceDeployments($serviceId: UUID!, $environmentId: UUID, $limit: Int) {
    serviceDeployments(serviceId: $serviceId, environmentId: $environmentId, limit: $limit) {
      ${DEPLOYMENT_FIELDS}
    }
  }
`;

export const SET_WORKLOAD_VERSION_MUTATION = `
  mutation SetWorkloadVersion($input: SetWorkloadVersionInput!) {
    setWorkloadVersion(input: $input) { ${DEPLOYMENT_FIELDS} }
  }
`;

export const ROLLBACK_WORKLOAD_MUTATION = `
  mutation RollbackWorkload($serviceId: UUID!, $environmentId: UUID!) {
    rollbackWorkload(serviceId: $serviceId, environmentId: $environmentId) { id version }
  }
`;

export const PROMOTE_WORKLOAD_MUTATION = `
  mutation PromoteWorkload($serviceId: UUID!, $environmentId: UUID!) {
    promoteWorkload(serviceId: $serviceId, environmentId: $environmentId) { id version environmentName }
  }
`;

export const CREATE_SERVICE_DEPLOY_TOKEN_MUTATION = `
  mutation CreateServiceDeployToken($serviceId: UUID!, $name: String!, $expiresInDays: Int!) {
    createServiceDeployToken(serviceId: $serviceId, name: $name, expiresInDays: $expiresInDays) {
      id
      name
      token
      tokenPrefix
      expiresAt
    }
  }
`;
