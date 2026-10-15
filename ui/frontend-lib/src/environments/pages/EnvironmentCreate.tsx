import { useCallback, useState } from "react";

import { Controller, useForm } from "react-hook-form";
import { useNavigate } from "react-router";

import {
  Box,
  Button,
  FormControlLabel,
  MenuItem,
  Switch,
  TextField,
} from "@mui/material";

import { LabelInput } from "../../common";
import { PropertyCard } from "../../common/components/cards/PropertyCard";
import ArrayReferenceInput from "../../common/components/inputs/ArrayReferenceInput";
import ReferenceInput from "../../common/components/inputs/ReferenceInput";
import { useConfig } from "../../common/context/ConfigContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import PageContainer from "../../common/PageContainer";
import { IkEntity } from "../../types";
import { CREATE_ENVIRONMENT_MUTATION } from "../graphql";
import { ENVIRONMENT_TIERS, EnvironmentCreateRequest } from "../types";

const OPTIONAL_KEYS = [
  "displayName",
  "projectId",
  "region",
  "accountId",
  "clusterName",
  "workspaceId",
  "storageId",
  "storagePathPrefix",
] as const;

const toInput = (data: EnvironmentCreateRequest): EnvironmentCreateRequest => {
  const input = { ...data, rank: Number(data.rank) || 0 };
  for (const key of OPTIONAL_KEYS) {
    if (!input[key]) input[key] = null;
  }
  return input;
};

export const EnvironmentCreatePage = () => {
  const { ikApi, linkPrefix } = useConfig();
  const navigate = useNavigate();
  const [buffer, setBuffer] = useState<Record<string, IkEntity | IkEntity[]>>(
    {},
  );

  const {
    control,
    handleSubmit,
    formState: { errors },
  } = useForm<EnvironmentCreateRequest>({
    defaultValues: {
      name: "",
      displayName: "",
      description: "",
      tier: "dev",
      rank: 0,
      projectId: "",
      region: "",
      accountId: "",
      clusterName: "",
      workspaceId: "",
      storageId: "",
      storagePathPrefix: "",
      integrationIds: [],
      parentResources: [],
      approvalRequired: false,
      labels: [],
    },
    mode: "onChange",
  });

  const onSubmit = useCallback(
    async (data: EnvironmentCreateRequest) => {
      try {
        const response = await ikApi.graphqlRequest<{
          createEnvironment: { id: string };
        }>(CREATE_ENVIRONMENT_MUTATION, { input: toInput(data) });

        if (response.createEnvironment?.id) {
          notify("Environment created successfully", "success");
          navigate(
            `${linkPrefix}environments/${response.createEnvironment.id}`,
          );
        }
      } catch (error: any) {
        notifyError(error);
      }
    },
    [ikApi, navigate, linkPrefix],
  );

  const text = (
    name: keyof EnvironmentCreateRequest,
    label: string,
    helperText: string,
    placeholder?: string,
  ) => (
    <Controller
      name={name}
      control={control}
      render={({ field }) => (
        <TextField
          {...field}
          value={field.value ?? ""}
          label={label}
          placeholder={placeholder}
          helperText={helperText}
          fullWidth
          margin="normal"
          slotProps={{ htmlInput: { "aria-label": label } }}
        />
      )}
    />
  );

  return (
    <PageContainer
      title="Create Environment"
      bottomActions={
        <>
          <Button onClick={() => navigate(`${linkPrefix}environments`)}>
            Cancel
          </Button>
          <Button variant="contained" onClick={handleSubmit(onSubmit)}>
            Save
          </Button>
        </>
      }
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          flexDirection: "column",
          width: "100%",
          minWidth: 320,
        }}
      >
        <PropertyCard title="Environment Definition">
          <Box>
            <Controller
              name="name"
              control={control}
              rules={{ required: "Name is required" }}
              render={({ field }) => (
                <TextField
                  {...field}
                  label="Name"
                  required
                  placeholder="app-staging-eu-central-1"
                  error={!!errors.name}
                  helperText={
                    errors.name?.message ??
                    "Unique across all environments. Include the region when a tier spans several."
                  }
                  fullWidth
                  margin="normal"
                  slotProps={{
                    htmlInput: { "aria-label": "Environment name" },
                  }}
                />
              )}
            />
            {text(
              "displayName",
              "Display Name",
              "Optional human-friendly name",
            )}
            {text("description", "Description", "What this environment is for")}
            <Controller
              name="tier"
              control={control}
              render={({ field }) => (
                <TextField
                  {...field}
                  select
                  label="Tier"
                  helperText="Groups environments for promotion: dev → staging → prod"
                  fullWidth
                  margin="normal"
                >
                  {ENVIRONMENT_TIERS.map((tier) => (
                    <MenuItem key={tier} value={tier}>
                      {tier}
                    </MenuItem>
                  ))}
                </TextField>
              )}
            />
            <Controller
              name="rank"
              control={control}
              rules={{ min: { value: 0, message: "Rank cannot be negative" } }}
              render={({ field }) => (
                <TextField
                  {...field}
                  type="number"
                  label="Rank"
                  error={!!errors.rank}
                  helperText={
                    errors.rank?.message ??
                    "Rollout order within the tier; lower goes first"
                  }
                  fullWidth
                  margin="normal"
                  slotProps={{ htmlInput: { min: 0 } }}
                />
              )}
            />
            <Controller
              name="projectId"
              control={control}
              render={({ field }) => (
                <ReferenceInput
                  ikApi={ikApi}
                  buffer={buffer}
                  setBuffer={setBuffer}
                  {...field}
                  entity_name="projects"
                  showFields={["name"]}
                  value={field.value}
                  label="Project (optional)"
                  helpertext="Leave empty to make this environment available to every project"
                />
              )}
            />
            <Controller
              name="labels"
              control={control}
              render={({ field }) => <LabelInput errors={errors} {...field} />}
            />
          </Box>
        </PropertyCard>

        <PropertyCard title="Target">
          <Box>
            {text("region", "Region", "Cloud region", "eu-central-1")}
            {text("accountId", "Account", "Cloud account or subscription ID")}
            {text(
              "clusterName",
              "Cluster",
              "Kubernetes cluster that workloads run on",
              "staging-eu-central-1-eks",
            )}
            <Controller
              name="parentResources"
              control={control}
              render={({ field }) => (
                <ArrayReferenceInput
                  ikApi={ikApi}
                  entity_name="resources"
                  showFields={["name"]}
                  buffer={buffer as Record<string, IkEntity[]>}
                  setBuffer={setBuffer}
                  value={field.value}
                  onChange={field.onChange}
                  label="Landing Zone"
                  ariaLabel="Landing zone resources"
                  placeholder="Select VPC, cluster…"
                  helpertext="Existing resources that infrastructure claimed in this environment attaches under, e.g. its VPC or EKS cluster"
                  multiple
                />
              )}
            />
            <Controller
              name="integrationIds"
              control={control}
              render={({ field }) => (
                <ArrayReferenceInput
                  ikApi={ikApi}
                  entity_name="integrations"
                  filter={{ integration_type: "cloud" }}
                  showFields={["integrationProvider", "name"]}
                  buffer={buffer as Record<string, IkEntity[]>}
                  setBuffer={setBuffer}
                  value={field.value}
                  onChange={field.onChange}
                  label="Default Integrations"
                  ariaLabel="Default integrations"
                  placeholder="Select credentials…"
                  helpertext="Cloud credentials used for resources provisioned in this environment"
                  multiple
                />
              )}
            />
          </Box>
        </PropertyCard>

        <PropertyCard title="State & Governance">
          <Box>
            <Controller
              name="storageId"
              control={control}
              render={({ field }) => (
                <ReferenceInput
                  ikApi={ikApi}
                  buffer={buffer}
                  setBuffer={setBuffer}
                  {...field}
                  entity_name="storages"
                  showFields={["name"]}
                  value={field.value}
                  label="State Storage (optional)"
                  helpertext="Where Terraform state for this environment is kept"
                />
              )}
            />
            {text(
              "storagePathPrefix",
              "Storage Path Prefix",
              "Prepended to state paths of newly claimed resources only; adopted resources keep their existing paths",
            )}
            <Controller
              name="workspaceId"
              control={control}
              render={({ field }) => (
                <ReferenceInput
                  ikApi={ikApi}
                  buffer={buffer}
                  setBuffer={setBuffer}
                  {...field}
                  entity_name="workspaces"
                  showFields={["name"]}
                  value={field.value}
                  label="Workspace (optional)"
                />
              )}
            />
            <Controller
              name="approvalRequired"
              control={control}
              render={({ field }) => (
                <FormControlLabel
                  sx={{ mt: 1 }}
                  control={
                    <Switch
                      checked={field.value}
                      onChange={(event) => field.onChange(event.target.checked)}
                    />
                  }
                  label="Require approval for infrastructure changes"
                />
              )}
            />
          </Box>
        </PropertyCard>
      </Box>
    </PageContainer>
  );
};

EnvironmentCreatePage.path = "environments/create";
