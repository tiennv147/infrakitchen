import { useCallback } from "react";

import { Box, Chip } from "@mui/material";

import { OverviewCard } from "../../common/components/cards/OverviewCard";
import { EditableDescriptionField } from "../../common/components/editors/EditableDescriptionField";
import { EditableTagsField } from "../../common/components/editors/EditableTagsField";
import {
  CommonField,
  GetReferenceUrlValue,
} from "../../common/components/fields/CommonField";
import { RelativeTime } from "../../common/components/fields/RelativeTime";
import { useConfig } from "../../common/context";
import { useEntityProvider } from "../../common/context/EntityContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import StatusChip from "../../common/StatusChip";
import { UPDATE_ENVIRONMENT_MUTATION } from "../graphql";
import { EnvironmentUpdateRequest, GqlEnvironment } from "../types";

const valueOrDash = (value: string | null | undefined) => value || "—";

export const EnvironmentOverview = ({
  environment,
}: {
  environment: GqlEnvironment;
}) => {
  const { ikApi } = useConfig();
  const { actions, refreshEntity } = useEntityProvider();
  const canEdit = actions.includes("edit");

  const saveField = useCallback(
    async (input: EnvironmentUpdateRequest) => {
      try {
        await ikApi.graphqlRequest(UPDATE_ENVIRONMENT_MUTATION, {
          id: environment.id,
          input,
        });
        notify("Environment updated successfully", "success");
        refreshEntity?.();
      } catch (error) {
        notifyError(error);
        throw error;
      }
    },
    [ikApi, environment.id, refreshEntity],
  );

  return (
    <OverviewCard name={environment.displayName || environment.name}>
      <CommonField
        name="Status"
        value={<StatusChip status={environment.status} />}
      />
      <CommonField
        name="Tier"
        value={<Chip size="small" label={environment.tier} />}
      />
      <CommonField name="Rank" value={environment.rank} />
      <EditableDescriptionField
        value={environment.description}
        canEdit={canEdit}
        onSave={(value) => saveField({ description: value })}
      />
      <CommonField name="Region" value={valueOrDash(environment.region)} />
      <CommonField name="Account" value={valueOrDash(environment.accountId)} />
      <CommonField
        name="Cluster"
        value={valueOrDash(environment.clusterName)}
      />
      <CommonField
        name="Approval Required"
        value={environment.approvalRequired ? "Yes" : "No"}
      />
      <CommonField
        name="Project"
        value={
          environment.project ? (
            <GetReferenceUrlValue
              {...environment.project}
              entityName="project"
            />
          ) : (
            "Global"
          )
        }
      />
      <CommonField
        name="Storage"
        value={
          environment.storage ? (
            <GetReferenceUrlValue
              {...environment.storage}
              entityName="storage"
            />
          ) : (
            "—"
          )
        }
      />
      <CommonField
        name="Storage Path Prefix"
        value={valueOrDash(environment.storagePathPrefix)}
      />
      <CommonField
        name="Landing Zone"
        size={12}
        value={
          environment.parentResources.length ? (
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1 }}>
              {environment.parentResources.map((resource) => (
                <GetReferenceUrlValue
                  key={resource.id}
                  {...resource}
                  entityName="resource"
                />
              ))}
            </Box>
          ) : (
            "No parent resources — claims will not attach to any landing zone"
          )
        }
      />
      <CommonField
        name="Created"
        value={<RelativeTime date={environment.createdAt} />}
      />
      <CommonField
        name="Last Updated"
        value={<RelativeTime date={environment.updatedAt} />}
      />
      <EditableTagsField
        name="Labels"
        value={environment.labels || []}
        canEdit={canEdit}
        onSave={(value) => saveField({ labels: value })}
        helperText="Press Enter to add a label"
      />
    </OverviewCard>
  );
};
