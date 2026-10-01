import { useCallback, useEffect, useState } from "react";

import {
  Box,
  MenuItem,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";

import { EntityGraphViewTab } from "../../common/components/graph/GraphViewTab";
import { TreeResponse } from "../../common/components/tree/types";
import { useConfig } from "../../common/context/ConfigContext";
import { notifyError } from "../../common/hooks/useNotification";
import { ENVIRONMENTS_SHORT_QUERY } from "../../environments/graphql";
import { GqlEnvironmentShort } from "../../environments/types";
import {
  GqlServiceGraphNode,
  RESOURCE_IMPACT_QUERY,
  SERVICE_GRAPH_QUERY,
} from "../graphql";

type Direction = "dependencies" | "dependents";

const HELP: Record<Direction, string> = {
  dependencies:
    "Services this one depends on, and the resources each uses. Dashed edges are shared resources the service only references.",
  dependents:
    "Every service that depends on this one, directly or not: what a change here can break.",
};

export const ServiceGraph = ({ serviceId }: { serviceId: string }) => {
  const { ikApi } = useConfig();
  const [direction, setDirection] = useState<Direction>("dependencies");
  const [environments, setEnvironments] = useState<GqlEnvironmentShort[]>([]);
  const [environmentId, setEnvironmentId] = useState("");

  useEffect(() => {
    ikApi
      .graphqlRequest<{ environments: GqlEnvironmentShort[] }>(
        ENVIRONMENTS_SHORT_QUERY,
        { sort: ["name", "ASC"], range: [0, 1000] },
      )
      .then((r) => setEnvironments(r.environments || []))
      .catch(notifyError);
  }, [ikApi]);

  const loadTree = useCallback(
    () =>
      ikApi
        .graphqlRequest<{ serviceGraph: GqlServiceGraphNode }>(
          SERVICE_GRAPH_QUERY,
          {
            id: serviceId,
            direction,
            environmentId: environmentId || null,
          },
        )
        .then((r) => r.serviceGraph),
    [ikApi, serviceId, direction, environmentId],
  );

  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}
    >
      <Box sx={{ display: "flex", gap: 2, alignItems: "center" }}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={direction}
          onChange={(_, value) => value && setDirection(value)}
        >
          <ToggleButton value="dependencies">Dependencies</ToggleButton>
          <ToggleButton value="dependents">Impact</ToggleButton>
        </ToggleButtonGroup>
        {direction === "dependencies" && (
          <TextField
            select
            size="small"
            label="Environment"
            sx={{ minWidth: 240 }}
            value={environmentId}
            onChange={(e) => setEnvironmentId(e.target.value)}
          >
            <MenuItem value="">All environments</MenuItem>
            {environments.map((env) => (
              <MenuItem key={env.id} value={env.id}>
                {env.displayName || env.name}
              </MenuItem>
            ))}
          </TextField>
        )}
      </Box>
      <Typography variant="body2" color="text.secondary">
        {HELP[direction]}
      </Typography>
      <EntityGraphViewTab
        entity_name="service"
        entity_id={serviceId}
        loadTree={loadTree}
      />
    </Box>
  );
};

export const ResourceImpactGraph = ({ resourceId }: { resourceId: string }) => {
  const { ikApi } = useConfig();
  const loadTree = useCallback(
    () =>
      ikApi
        .graphqlRequest<{ resourceImpact: TreeResponse }>(
          RESOURCE_IMPACT_QUERY,
          { id: resourceId },
        )
        .then((r) => r.resourceImpact),
    [ikApi, resourceId],
  );

  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}
    >
      <Typography variant="body2" color="text.secondary">
        Services that own or reference this resource, and the services that
        depend on them: what breaks if this resource changes.
      </Typography>
      <EntityGraphViewTab
        entity_name="resource"
        entity_id={resourceId}
        loadTree={loadTree}
      />
    </Box>
  );
};
