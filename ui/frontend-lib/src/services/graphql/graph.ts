import { TreeResponse } from "../../common/components/tree/types";

const NODE_FIELDS =
  "id nodeId name entityName relation state status templateName";

// GraphQL has no recursive selections; MAX_DEPTH on the server is 5, so 6 levels cover any tree.
const treeFields = (depth: number): string =>
  depth === 0
    ? NODE_FIELDS
    : `${NODE_FIELDS} children { ${treeFields(depth - 1)} }`;

export type GqlServiceGraphNode = TreeResponse;

export const SERVICE_GRAPH_QUERY = `
  query ServiceGraph($id: UUID!, $direction: String!, $environmentId: UUID) {
    serviceGraph(id: $id, direction: $direction, environmentId: $environmentId) {
      ${treeFields(6)}
    }
  }
`;

export const RESOURCE_IMPACT_QUERY = `
  query ResourceImpact($id: UUID!) {
    resourceImpact(id: $id) {
      ${treeFields(7)}
    }
  }
`;
