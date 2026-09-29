import { useState } from "react";

import {
  Autocomplete,
  Box,
  Chip,
  FormControlLabel,
  MenuItem,
  Switch,
  TextField,
  Typography,
} from "@mui/material";

import { InlineCode } from "../../common/components/code/InlineCode";
import { useConfig } from "../../common/context/ConfigContext";
import { notifyError } from "../../common/hooks/useNotification";
import { BindingSinkConfig, BindingSinkType } from "../types";

const SINK_LABELS: Record<BindingSinkType, string> = {
  aws_secrets_manager: "AWS Secrets Manager",
  kubernetes_secret: "Kubernetes Secret",
  none: "Disabled",
};

export const BindingSinkSummary = ({
  config,
}: {
  config: BindingSinkConfig;
}) => {
  const type = config.type ?? "aws_secrets_manager";
  if (type === "none") return <Typography variant="body2">Disabled</Typography>;
  return (
    <Box
      sx={{ display: "flex", gap: 1, alignItems: "center", flexWrap: "wrap" }}
    >
      <Chip size="small" label={SINK_LABELS[type]} />
      <InlineCode>{config.path_template ?? "config-{service_name}"}</InlineCode>
      {config.secret_provider_class && (
        <Chip
          size="small"
          variant="outlined"
          label="manages SecretProviderClass"
        />
      )}
    </Box>
  );
};

const EKS_QUERY = `
  query EksClusters($filter: JSON) {
    resources(filter: $filter, range: [0, 50], sort: ["name", "ASC"]) { id name }
  }
`;

export const BindingSinkEditor = ({
  value,
  onChange,
}: {
  value: BindingSinkConfig;
  onChange: (value: BindingSinkConfig) => void;
}) => {
  const { ikApi } = useConfig();
  const [clusters, setClusters] = useState<{ id: string; name: string }[]>([]);
  const type = value.type ?? "aws_secrets_manager";
  const needsCluster =
    type === "kubernetes_secret" || !!value.secret_provider_class;
  const set = (patch: Partial<BindingSinkConfig>) =>
    onChange({ ...value, ...patch });

  const searchClusters = (text: string) => {
    if (text.trim().length < 2) return;
    ikApi
      .graphqlRequest<{ resources: { id: string; name: string }[] }>(
        EKS_QUERY,
        {
          filter: { template__template: "aws_eks", name__like: text.trim() },
        },
      )
      .then((r) => setClusters(r.resources || []))
      .catch(notifyError);
  };

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        gap: 2,
        width: "100%",
        pt: 1,
      }}
    >
      <Box sx={{ display: "flex", gap: 2 }}>
        <TextField
          select
          label="Sink"
          value={type}
          onChange={(e) => set({ type: e.target.value as BindingSinkType })}
          sx={{ minWidth: 220 }}
        >
          {Object.entries(SINK_LABELS).map(([key, label]) => (
            <MenuItem key={key} value={key}>
              {label}
            </MenuItem>
          ))}
        </TextField>
        {type !== "none" && (
          <TextField
            fullWidth
            label="Path"
            value={value.path_template ?? "config-{service_name}"}
            onChange={(e) => set({ path_template: e.target.value })}
            helperText="Placeholders: {service_name}, {environment}, {region}"
          />
        )}
      </Box>
      {type !== "none" && (
        <>
          {type === "aws_secrets_manager" && (
            <FormControlLabel
              control={
                <Switch
                  checked={!!value.secret_provider_class}
                  onChange={(e) =>
                    set({ secret_provider_class: e.target.checked })
                  }
                />
              }
              label="Create the service's SecretProviderClass when it does not exist"
            />
          )}
          {needsCluster && (
            <Box sx={{ display: "flex", gap: 2 }}>
              <Autocomplete
                sx={{ flex: 1 }}
                options={clusters}
                getOptionLabel={(o) => o.name}
                value={
                  clusters.find((c) => c.id === value.cluster_resource_id) ??
                  null
                }
                onInputChange={(_, text) => searchClusters(text)}
                onChange={(_, cluster) =>
                  set({ cluster_resource_id: cluster?.id ?? null })
                }
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="EKS cluster resource"
                    helperText={
                      value.cluster_resource_id && !clusters.length
                        ? `Selected: ${value.cluster_resource_id}`
                        : "Type to search aws_eks resources"
                    }
                  />
                )}
              />
              <TextField
                sx={{ flex: 1 }}
                label="Namespace"
                value={value.namespace ?? ""}
                onChange={(e) => set({ namespace: e.target.value || null })}
                helperText="Defaults to the service name"
              />
            </Box>
          )}
        </>
      )}
    </Box>
  );
};
