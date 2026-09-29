import { useEffect, useState } from "react";

import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  MenuItem,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";

import { CommonDialog } from "../../common/components/dialogs/CommonDialog";
import { useConfig } from "../../common/context/ConfigContext";
import { notifyError } from "../../common/hooks/useNotification";
import { ENVIRONMENTS_SHORT_QUERY } from "../../environments/graphql";
import { GqlEnvironmentShort } from "../../environments/types";
import {
  GqlServicePlan,
  GqlServicePlanItem,
  SERVICE_PLAN_QUERY,
} from "../graphql";

const ACTION_COLOR: Record<
  GqlServicePlanItem["action"],
  "success" | "warning" | "default" | "error"
> = {
  create: "success",
  update: "warning",
  no_op: "default",
  destroy: "error",
};

const ACTION_LABEL: Record<GqlServicePlanItem["action"], string> = {
  create: "create",
  update: "update",
  no_op: "no change",
  destroy: "destroy",
};

const formatValue = (value: unknown) =>
  value === null || value === undefined ? "—" : JSON.stringify(value);

interface ServicePlanDialogProps {
  open: boolean;
  serviceId: string;
  initialEnvironmentId?: string;
  onClose: () => void;
}

export const ServicePlanDialog = ({
  open,
  serviceId,
  initialEnvironmentId,
  onClose,
}: ServicePlanDialogProps) => {
  const { ikApi } = useConfig();
  const [environments, setEnvironments] = useState<GqlEnvironmentShort[]>([]);
  const [environmentId, setEnvironmentId] = useState("");
  const [plan, setPlan] = useState<GqlServicePlan | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPlan(null);
    setEnvironmentId(initialEnvironmentId ?? "");
    ikApi
      .graphqlRequest<{ environments: GqlEnvironmentShort[] }>(
        ENVIRONMENTS_SHORT_QUERY,
        { sort: ["name", "ASC"], range: [0, 1000] },
      )
      .then((response) =>
        setEnvironments(
          (response.environments || []).filter(
            (e) => e.status?.toLowerCase() === "enabled",
          ),
        ),
      )
      .catch(notifyError);
  }, [ikApi, open, initialEnvironmentId]);

  useEffect(() => {
    if (!open || !environmentId) return;
    setLoading(true);
    ikApi
      .graphqlRequest<{ servicePlan: GqlServicePlan }>(SERVICE_PLAN_QUERY, {
        serviceId,
        environmentId,
      })
      .then((response) => setPlan(response.servicePlan))
      .catch((error) => {
        setPlan(null);
        notifyError(error);
      })
      .finally(() => setLoading(false));
  }, [ikApi, open, serviceId, environmentId]);

  return (
    <CommonDialog
      open={open}
      onClose={onClose}
      maxWidth="lg"
      title="Plan preview"
      content={
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 2 }}>
          <Typography variant="body2" color="text.secondary">
            A dry run of the service spec against one environment. Nothing is
            created, changed or destroyed.
          </Typography>
          <TextField
            select
            size="small"
            label="Environment"
            value={environmentId}
            onChange={(event) => setEnvironmentId(event.target.value)}
            sx={{ maxWidth: 360 }}
          >
            {environments.map((environment) => (
              <MenuItem key={environment.id} value={environment.id}>
                {environment.displayName || environment.name}
                {environment.region ? ` · ${environment.region}` : ""}
              </MenuItem>
            ))}
          </TextField>

          {loading && (
            <Box sx={{ display: "flex", justifyContent: "center", py: 3 }}>
              <CircularProgress />
            </Box>
          )}

          {!loading && plan && (
            <>
              {!plan.serviceInstanceId && (
                <Alert severity="info">
                  The service is not deployed to this environment yet; every
                  claim would be created.
                </Alert>
              )}
              {plan.errors.map((error) => (
                <Alert key={error} severity="error">
                  {error}
                </Alert>
              ))}
              <Box sx={{ display: "flex", gap: 1 }}>
                <Chip color="success" label={`${plan.creates} to create`} />
                <Chip color="warning" label={`${plan.updates} to update`} />
                <Chip label={`${plan.noOps} unchanged`} />
                <Chip color="error" label={`${plan.destroys} to destroy`} />
              </Box>
              {plan.items.length > 0 && (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Claim</TableCell>
                      <TableCell>Action</TableCell>
                      <TableCell>Offering</TableCell>
                      <TableCell>Placement</TableCell>
                      <TableCell>Changes</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {plan.items.map((item) => (
                      <TableRow key={item.alias}>
                        <TableCell>
                          <Typography variant="body2">{item.alias}</Typography>
                          {item.resourceName && (
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              {item.resourceName}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>
                          <Chip
                            size="small"
                            color={ACTION_COLOR[item.action]}
                            label={ACTION_LABEL[item.action]}
                          />
                        </TableCell>
                        <TableCell>{item.template || "—"}</TableCell>
                        <TableCell>
                          {item.parents.map((parent) => (
                            <Typography
                              key={parent}
                              variant="caption"
                              component="div"
                            >
                              parent {parent}
                            </Typography>
                          ))}
                          {item.storagePath && (
                            <Typography
                              variant="caption"
                              component="div"
                              sx={{ fontFamily: "monospace" }}
                            >
                              {item.storagePath}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>
                          {item.wires.map((wire) => (
                            <Typography
                              key={wire}
                              variant="caption"
                              component="div"
                              sx={{ fontFamily: "monospace" }}
                            >
                              {wire}
                            </Typography>
                          ))}
                          {item.changes.map((change) => (
                            <Typography
                              key={change.field}
                              variant="caption"
                              component="div"
                              sx={{ fontFamily: "monospace" }}
                            >
                              {change.field}: {formatValue(change.before)} →{" "}
                              {formatValue(change.after)}
                            </Typography>
                          ))}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </>
          )}
        </Box>
      }
    />
  );
};
