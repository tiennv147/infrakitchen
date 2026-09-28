import { ENVIRONMENT_SHORT_FIELDS } from "../../environments/graphql/fragments";
import { GqlEnvironmentShort } from "../../environments/types";

export interface GqlServiceInstance {
  id: string;
  state: string;
  status: string;
  createdAt: string;
  environment: GqlEnvironmentShort | null;
  resources: { id: string; alias: string; role: string }[];
}

export const SERVICE_INSTANCES_QUERY = `
  query ServiceInstances($filter: JSON, $sort: [String!], $range: [Int!]) {
    serviceInstances(filter: $filter, sort: $sort, range: $range) {
      id
      state
      status
      createdAt
      environment { ${ENVIRONMENT_SHORT_FIELDS} }
      resources { id alias role }
    }
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
