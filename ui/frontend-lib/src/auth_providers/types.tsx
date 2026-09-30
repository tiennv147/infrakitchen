export interface AuthProviderCreate {
  name: string;
  description: string;
  configuration: object;
  authProvider:
    | "microsoft"
    | "guest"
    | "github"
    | "google"
    | "gitlab"
    | "backstage"
    | "ik_service_account"
    | "github_oidc"
    | "";
  filterByDomain: string[];
  enabled: boolean;
}
