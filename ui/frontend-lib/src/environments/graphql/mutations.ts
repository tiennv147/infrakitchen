export const CREATE_ENVIRONMENT_MUTATION = `
  mutation CreateEnvironment($input: EnvironmentCreateInput!) {
    createEnvironment(input: $input) {
      id
      name
      entityName
    }
  }
`;

export const UPDATE_ENVIRONMENT_MUTATION = `
  mutation UpdateEnvironment($id: UUID!, $input: EnvironmentUpdateInput!) {
    updateEnvironment(id: $id, input: $input) {
      id
    }
  }
`;
