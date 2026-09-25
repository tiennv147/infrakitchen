import { USER_SHORT_FIELDS } from "../../users/graphql";

const REF_FIELDS = `
  id
  name
`;

export const ENVIRONMENT_SHORT_FIELDS = `
  id
  name
  displayName
  tier
  region
  status
  entityName
`;

export const ENVIRONMENT_LIST_FIELDS = `
  ${ENVIRONMENT_SHORT_FIELDS}
  description
  rank
  clusterName
  labels
  updatedAt
`;

export const ENVIRONMENT_DETAIL_FIELDS = `
  ${ENVIRONMENT_SHORT_FIELDS}
  description
  rank
  projectId
  accountId
  clusterName
  workspaceId
  storageId
  storagePathPrefix
  approvalRequired
  labels
  revisionNumber
  createdAt
  updatedAt
  creator { ${USER_SHORT_FIELDS} }
  project { ${REF_FIELDS} }
  workspace { ${REF_FIELDS} }
  storage { ${REF_FIELDS} }
  integrationIds { ${REF_FIELDS} }
  parentResources { ${REF_FIELDS} }
`;
