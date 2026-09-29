import { useCallback, useEffect, useMemo, useState } from "react";

import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";

import { CommonDialog } from "../../common/components/dialogs/CommonDialog";
import { GetReferenceUrlValue } from "../../common/components/fields/CommonField";
import { RelativeTime } from "../../common/components/fields/RelativeTime";
import { useConfig } from "../../common/context/ConfigContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import StatusChip from "../../common/StatusChip";
import { ENVIRONMENTS_SHORT_QUERY } from "../../environments/graphql";
import { GqlEnvironmentShort } from "../../environments/types";
import {
  CREATE_SERVICE_INSTANCE_MUTATION,
  DELETE_SERVICE_INSTANCE_MUTATION,
  GqlServiceInstance,
  SERVICE_INSTANCES_QUERY,
} from "../graphql";

interface ServiceEnvironmentsProps {
  serviceId: string;
  canEdit: boolean;
}

const TIER_ORDER = { dev: 0, staging: 1, prod: 2 } as const;

const byPromotionOrder = (a: GqlEnvironmentShort, b: GqlEnvironmentShort) =>
  TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || a.name.localeCompare(b.name);

export const ServiceEnvironments = ({
  serviceId,
  canEdit,
}: ServiceEnvironmentsProps) => {
  const { ikApi } = useConfig();
  const [instances, setInstances] = useState<GqlServiceInstance[]>([]);
  const [environments, setEnvironments] = useState<GqlEnvironmentShort[]>([]);
  const [selected, setSelected] = useState("");
  const [pendingRemoval, setPendingRemoval] =
    useState<GqlServiceInstance | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setError(null);
    try {
      const [instanceResponse, environmentResponse] = await Promise.all([
        ikApi.graphqlRequest<{ serviceInstances: GqlServiceInstance[] }>(
          SERVICE_INSTANCES_QUERY,
          { filter: { service_id: [serviceId] }, range: [0, 1000] },
        ),
        ikApi.graphqlRequest<{ environments: GqlEnvironmentShort[] }>(
          ENVIRONMENTS_SHORT_QUERY,
          { sort: ["name", "ASC"], range: [0, 1000] },
        ),
      ]);
      setInstances(instanceResponse.serviceInstances || []);
      setEnvironments(environmentResponse.environments || []);
    } catch (error: any) {
      setError(error.message || "Failed to load environments");
      notifyError(error);
    } finally {
      setLoading(false);
    }
  }, [ikApi, serviceId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const deployedIds = useMemo(
    () => new Set(instances.map((instance) => instance.environment?.id)),
    [instances],
  );

  const available = useMemo(
    () =>
      environments
        .filter(
          (environment) =>
            environment.status?.toLowerCase() === "enabled" &&
            !deployedIds.has(environment.id),
        )
        .sort(byPromotionOrder),
    [environments, deployedIds],
  );

  const sortedInstances = useMemo(
    () =>
      [...instances].sort((a, b) =>
        a.environment && b.environment
          ? byPromotionOrder(a.environment, b.environment)
          : 0,
      ),
    [instances],
  );

  const addEnvironment = async () => {
    if (!selected) return;
    try {
      await ikApi.graphqlRequest(CREATE_SERVICE_INSTANCE_MUTATION, {
        input: { serviceId, environmentId: selected },
      });
      notify("Environment added", "success");
      setSelected("");
      fetchData();
    } catch (error) {
      notifyError(error);
    }
  };

  const removeEnvironment = async () => {
    if (!pendingRemoval) return;
    try {
      await ikApi.graphqlRequest(DELETE_SERVICE_INSTANCE_MUTATION, {
        id: pendingRemoval.id,
      });
      notify("Environment removed", "success");
      fetchData();
    } catch (error) {
      notifyError(error);
    } finally {
      setPendingRemoval(null);
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ py: 2 }}>
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
        <Button onClick={fetchData}>Retry</Button>
      </Box>
    );
  }

  return (
    <Box sx={{ width: "100%" }}>
      {canEdit && (
        <Box sx={{ display: "flex", gap: 1, alignItems: "center", mb: 2 }}>
          <TextField
            select
            size="small"
            label="Add environment"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            sx={{ minWidth: 320 }}
            disabled={available.length === 0}
            helperText={
              available.length === 0
                ? "Deployed to every enabled environment"
                : undefined
            }
          >
            {available.map((environment) => (
              <MenuItem key={environment.id} value={environment.id}>
                {environment.displayName || environment.name}
                {environment.region ? ` · ${environment.region}` : ""}
              </MenuItem>
            ))}
          </TextField>
          <Button
            startIcon={<AddIcon />}
            onClick={addEnvironment}
            disabled={!selected}
          >
            Add
          </Button>
        </Box>
      )}

      {sortedInstances.length === 0 ? (
        <Box sx={{ textAlign: "center", py: 4 }}>
          <Typography variant="h6" component="p">
            This service is not deployed to any environment yet
          </Typography>
        </Box>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Environment</TableCell>
              <TableCell>Tier</TableCell>
              <TableCell>Region</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Resources</TableCell>
              <TableCell>Added</TableCell>
              {canEdit && <TableCell />}
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedInstances.map((instance) => (
              <TableRow key={instance.id}>
                <TableCell>
                  {instance.environment ? (
                    <GetReferenceUrlValue
                      id={instance.environment.id}
                      name={
                        instance.environment.displayName ||
                        instance.environment.name
                      }
                      entityName="environment"
                    />
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell>
                  {instance.environment && (
                    <Chip size="small" label={instance.environment.tier} />
                  )}
                </TableCell>
                <TableCell>{instance.environment?.region || "—"}</TableCell>
                <TableCell>
                  <StatusChip status={instance.status} state={instance.state} />
                </TableCell>
                <TableCell>{instance.resources.length}</TableCell>
                <TableCell>
                  <RelativeTime date={instance.createdAt} />
                </TableCell>
                {canEdit && (
                  <TableCell align="right">
                    <Tooltip title="Remove environment">
                      <IconButton
                        size="small"
                        aria-label="Remove environment"
                        onClick={() => setPendingRemoval(instance)}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      <CommonDialog
        open={pendingRemoval !== null}
        onClose={() => setPendingRemoval(null)}
        title="Remove environment"
        content={
          <Typography>
            Remove this service from{" "}
            <strong>
              {pendingRemoval?.environment?.displayName ||
                pendingRemoval?.environment?.name}
            </strong>
            ? Environments that still own resources cannot be removed.
          </Typography>
        }
        actions={
          <Button color="error" variant="contained" onClick={removeEnvironment}>
            Remove
          </Button>
        }
      />
    </Box>
  );
};
