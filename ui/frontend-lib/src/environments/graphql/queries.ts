import { ENVIRONMENT_LIST_FIELDS, ENVIRONMENT_SHORT_FIELDS } from "./fragments";

export const ENVIRONMENTS_QUERY = `
  query Environments($filter: JSON, $sort: [String!], $range: [Int!]) {
    environments(filter: $filter, sort: $sort, range: $range) {
      ${ENVIRONMENT_LIST_FIELDS}
    }
  }
`;

export const ENVIRONMENTS_SHORT_QUERY = `
  query EnvironmentsShort($filter: JSON, $sort: [String!], $range: [Int!]) {
    environments(filter: $filter, sort: $sort, range: $range) {
      ${ENVIRONMENT_SHORT_FIELDS}
    }
  }
`;
