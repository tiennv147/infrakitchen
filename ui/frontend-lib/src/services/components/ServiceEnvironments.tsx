import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import AddIcon from "@mui/icons-material/Add";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Link,
  Menu,
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

import { EntityLogs } from "../../common/components/activity/EntityLogs";
import { CommonDialog } from "../../common/components/dialogs/CommonDialog";
import { GetReferenceUrlValue } from "../../common/components/fields/CommonField";
import { RelativeTime } from "../../common/components/fields/RelativeTime";
import { useConfig } from "../../common/context/ConfigContext";
import { useEventProvider } from "../../common/context/EventContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import StatusChip from "../../common/StatusChip";
import { ENVIRONMENTS_SHORT_QUERY } from "../../environments/graphql";
import { GqlEnvironmentShort } from "../../environments/types";
import {
  CREATE_SERVICE_INSTANCE_MUTATION,
  DELETE_SERVICE_INSTANCE_MUTATION,
  GqlServiceInstance,
  SERVICE_INSTANCE_ACTION_MUTATION,
  SERVICE_INSTANCE_ACTIONS_QUERY,
  SERVICE_INSTANCES_QUERY,
} from "../graphql";

import { AdoptResourcesDialog } from "./AdoptResourcesDialog";
import { ServicePlanDialog } from "./ServicePlanDialog";

interface ServiceEnvironmentsProps {
  serviceId: string;
  specRevision: number;
  canEdit: boolean;
}

const TIER_ORDER = { dev: 0, staging: 1, prod: 2 } as const;

const byPromotionOrder = (a: GqlEnvironmentShort, b: GqlEnvironmentShort) =>
  TIER_ORDER[a.tier] - TIER_ORDER[b.tier] || a.name.localeCompare(b.name);

const envLabel = (instance: GqlServiceInstance | null) =>
  instance?.environment?.displayName || instance?.environment?.name || "";

const CONFIRM: Record<
  string,
  { title: string; text: string; color: "error" | "primary" }
> = {
  destroy: {
    title: "Destroy",
    text: "destroys every resource the service owns in this environment. Referenced resources are left untouched.",
    color: "error",
  },
  delete: {
    title: "Remove environment",
    text: "removes this environment from the service. Nothing is destroyed.",
    color: "error",
  },
};

const actionLabel = (action: string, instance: GqlServiceInstance) => {
  switch (action) {
    case "execute":
      return instance.specRevisionApplied === null ? "Deploy" : "Reconcile";
    case "dryrun":
      return "Plan";
    case "adopt":
      return "Adopt resources";
    case "delete":
      return "Remove";
    default:
      return action.charAt(0).toUpperCase() + action.slice(1);
  }
};

const PRIMARY = ["approve", "retry", "execute"];

export const ServiceEnvironments = ({
  serviceId,
  specRevision,
  canEdit,
}: ServiceEnvironmentsProps) => {
  const { ikApi, linkPrefix } = useConfig();
  const { event } = useEventProvider();
  const [instances, setInstances] = useState<GqlServiceInstance[]>([]);
  const [actions, setActions] = useState<Record<string, string[]>>({});
  const [environments, setEnvironments] = useState<GqlEnvironmentShort[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState<{
    anchor: HTMLElement;
    instance: GqlServiceInstance;
  } | null>(null);
  const [confirm, setConfirm] = useState<{
    action: string;
    instance: GqlServiceInstance;
  } | null>(null);
  const [planFor, setPlanFor] = useState<string | null>(null);
  const [adoptFor, setAdoptFor] = useState<GqlServiceInstance | null>(null);
  const [logsFor, setLogsFor] = useState<GqlServiceInstance | null>(null);

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
      const loaded = instanceResponse.serviceInstances || [];
      const actionLists = await Promise.all(
        loaded.map((instance) =>
          ikApi
            .graphqlRequest<{ serviceInstanceActions: string[] }>(
              SERVICE_INSTANCE_ACTIONS_QUERY,
              { id: instance.id },
            )
            .then((r) => [instance.id, r.serviceInstanceActions] as const),
        ),
      );
      setInstances(loaded);
      setActions(Object.fromEntries(actionLists));
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

  const instanceIds = useMemo(
    () => new Set(instances.map((instance) => instance.id)),
    [instances],
  );
  const refetchTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (
      event?._entity_name === "service_instance" &&
      instanceIds.has(event.id)
    ) {
      clearTimeout(refetchTimer.current);
      refetchTimer.current = setTimeout(fetchData, 300);
    }
  }, [event, instanceIds, fetchData]);

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

  const run = async (action: string, instance: GqlServiceInstance) => {
    setMenu(null);
    if (action === "dryrun") {
      setPlanFor(instance.environment?.id ?? null);
      return;
    }
    if (action === "adopt") {
      setAdoptFor(instance);
      return;
    }
    if (CONFIRM[action] && confirm?.instance.id !== instance.id) {
      setConfirm({ action, instance });
      return;
    }
    setConfirm(null);
    try {
      if (action === "delete") {
        await ikApi.graphqlRequest(DELETE_SERVICE_INSTANCE_MUTATION, {
          id: instance.id,
        });
        notify("Environment removed", "success");
      } else {
        const result = await ikApi.graphqlRequest<{
          serviceInstanceAction: { status: string };
        }>(SERVICE_INSTANCE_ACTION_MUTATION, {
          id: instance.id,
          input: { action },
        });
        const status = result.serviceInstanceAction.status.toLowerCase();
        notify(
          status === "approval_pending"
            ? "Waiting for approval"
            : `${actionLabel(action, instance)} started`,
          "success",
        );
      }
      fetchData();
    } catch (error) {
      notifyError(error);
    }
  };

  const driftChip = (instance: GqlServiceInstance) => {
    const state = instance.state.toLowerCase();
    if (state === "destroyed") return null;
    if (instance.specRevisionApplied === null) {
      return <Chip size="small" variant="outlined" label="Not deployed" />;
    }
    if (instance.specRevisionApplied !== specRevision) {
      return (
        <Tooltip title="The spec changed since the last successful deploy; reconcile to apply it">
          <Chip
            size="small"
            color="warning"
            label="Out of date"
            onClick={() => setPlanFor(instance.environment?.id ?? null)}
          />
        </Tooltip>
      );
    }
    return (
      <Chip
        size="small"
        color="success"
        variant="outlined"
        label="Up to date"
      />
    );
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
              <TableCell>Spec</TableCell>
              <TableCell>Resources</TableCell>
              <TableCell>Added</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {sortedInstances.map((instance) => {
              const instanceActions = actions[instance.id] || [];
              const primary = PRIMARY.find((a) => instanceActions.includes(a));
              const secondary = instanceActions.filter((a) => a !== primary);
              const owned = instance.resources.filter(
                (r) => r.role !== "referenced",
              ).length;
              return (
                <TableRow key={instance.id}>
                  <TableCell>
                    {instance.environment ? (
                      <GetReferenceUrlValue
                        id={instance.environment.id}
                        name={envLabel(instance)}
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
                    <StatusChip
                      status={instance.status}
                      state={instance.state}
                    />
                  </TableCell>
                  <TableCell>{driftChip(instance)}</TableCell>
                  <TableCell>
                    <Tooltip
                      title={instance.resources
                        .map((r) => `${r.alias} (${r.role})`)
                        .join(", ")}
                    >
                      <span>
                        {owned} owned
                        {instance.resources.length > owned
                          ? ` · ${instance.resources.length - owned} referenced`
                          : ""}
                      </span>
                    </Tooltip>
                  </TableCell>
                  <TableCell>
                    <RelativeTime date={instance.createdAt} />
                  </TableCell>
                  <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                    {primary && (
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={() => run(primary, instance)}
                      >
                        {actionLabel(primary, instance)}
                      </Button>
                    )}
                    <IconButton
                      size="small"
                      aria-label={`More actions for ${envLabel(instance)}`}
                      onClick={(e) =>
                        setMenu({ anchor: e.currentTarget, instance })
                      }
                    >
                      <MoreVertIcon fontSize="small" />
                    </IconButton>
                    {menu?.instance.id === instance.id && (
                      <Menu
                        anchorEl={menu.anchor}
                        open
                        onClose={() => setMenu(null)}
                      >
                        {secondary.map((action) => (
                          <MenuItem
                            key={action}
                            onClick={() => run(action, instance)}
                            sx={
                              CONFIRM[action]
                                ? { color: "error.main" }
                                : undefined
                            }
                          >
                            {actionLabel(action, instance)}
                          </MenuItem>
                        ))}
                        <MenuItem
                          onClick={() => {
                            setMenu(null);
                            setLogsFor(instance);
                          }}
                        >
                          Logs
                        </MenuItem>
                      </Menu>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}

      <CommonDialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        title={confirm ? CONFIRM[confirm.action].title : ""}
        content={
          <Typography>
            This {confirm ? CONFIRM[confirm.action].text : ""} Environment:{" "}
            <strong>{envLabel(confirm?.instance ?? null)}</strong>
          </Typography>
        }
        actions={
          <Button
            color={confirm ? CONFIRM[confirm.action].color : "primary"}
            variant="contained"
            onClick={() => confirm && run(confirm.action, confirm.instance)}
          >
            {confirm ? CONFIRM[confirm.action].title : ""}
          </Button>
        }
      />

      <ServicePlanDialog
        open={planFor !== null}
        serviceId={serviceId}
        initialEnvironmentId={planFor ?? undefined}
        onClose={() => setPlanFor(null)}
      />

      {adoptFor && (
        <AdoptResourcesDialog
          open
          serviceId={serviceId}
          environmentId={adoptFor.environment?.id ?? ""}
          environmentName={envLabel(adoptFor)}
          onClose={() => setAdoptFor(null)}
          onAdopted={() => {
            setAdoptFor(null);
            fetchData();
          }}
        />
      )}

      <CommonDialog
        open={logsFor !== null}
        onClose={() => setLogsFor(null)}
        maxWidth="lg"
        title={`Logs · ${envLabel(logsFor)}`}
        content={
          logsFor && (
            <Box
              sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 1 }}
            >
              <Typography variant="subtitle2">Reconciler</Typography>
              <EntityLogs entityId={logsFor.id} />
              {logsFor.workflowId && (
                <>
                  <Typography variant="subtitle2">
                    Latest workflow ·{" "}
                    <Link href={`${linkPrefix}workflows/${logsFor.workflowId}`}>
                      open
                    </Link>
                  </Typography>
                  <EntityLogs
                    traceId={logsFor.workflowId}
                    sourceCodeLanguage="opentofu"
                  />
                </>
              )}
            </Box>
          )
        }
      />
    </Box>
  );
};
