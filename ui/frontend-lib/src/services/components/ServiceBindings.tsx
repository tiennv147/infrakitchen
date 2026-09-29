import { useEffect, useMemo, useState } from "react";

import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
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

import { InlineCode } from "../../common/components/code/InlineCode";
import { RelativeTime } from "../../common/components/fields/RelativeTime";
import { useConfig } from "../../common/context/ConfigContext";
import { useEntityProvider } from "../../common/context/EntityContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import { ENVIRONMENTS_SHORT_QUERY } from "../../environments/graphql";
import { GqlEnvironmentShort } from "../../environments/types";
import {
  CLAIMABLE_TEMPLATES_QUERY,
  GqlBindingItem,
  GqlClaimableTemplate,
  GqlServiceBindings,
  SERVICE_BINDINGS_QUERY,
  UPDATE_SERVICE_MUTATION,
} from "../graphql";
import { BindingSpec, ServiceSpec } from "../types";

const KEY_PATTERN = /^[A-Za-z_][A-Za-z0-9_.-]{0,127}$/;
const REF = /\$\{([a-z][a-z0-9_]*)\.outputs\.([A-Za-z_][A-Za-z0-9_]*)\}/g;

const SINK_LABELS: Record<string, string> = {
  aws_secrets_manager: "AWS Secrets Manager",
  kubernetes_secret: "Kubernetes Secret",
  none: "Disabled",
};

interface ServiceBindingsProps {
  serviceId: string;
  spec: ServiceSpec | null;
  canEdit: boolean;
}

export const ServiceBindings = ({
  serviceId,
  spec,
  canEdit,
}: ServiceBindingsProps) => {
  const { ikApi } = useConfig();
  const { refreshEntity } = useEntityProvider();
  const saved = useMemo(() => spec?.bindings ?? [], [spec]);
  const [rows, setRows] = useState<BindingSpec[]>(saved);
  const [templates, setTemplates] = useState<GqlClaimableTemplate[]>([]);
  const [environments, setEnvironments] = useState<GqlEnvironmentShort[]>([]);
  const [environmentId, setEnvironmentId] = useState("");
  const [preview, setPreview] = useState<GqlServiceBindings | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => setRows(saved), [saved]);

  useEffect(() => {
    Promise.all([
      ikApi.graphqlRequest<{ claimableTemplates: GqlClaimableTemplate[] }>(
        CLAIMABLE_TEMPLATES_QUERY,
      ),
      ikApi.graphqlRequest<{ environments: GqlEnvironmentShort[] }>(
        ENVIRONMENTS_SHORT_QUERY,
        {
          sort: ["name", "ASC"],
          range: [0, 1000],
        },
      ),
    ])
      .then(([t, e]) => {
        setTemplates(t.claimableTemplates || []);
        setEnvironments(e.environments || []);
      })
      .catch(notifyError);
  }, [ikApi]);

  useEffect(() => {
    if (!environmentId) return;
    setLoading(true);
    ikApi
      .graphqlRequest<{ serviceBindings: GqlServiceBindings }>(
        SERVICE_BINDINGS_QUERY,
        {
          serviceId,
          environmentId,
        },
      )
      .then((r) => setPreview(r.serviceBindings))
      .catch((error) => {
        setPreview(null);
        notifyError(error);
      })
      .finally(() => setLoading(false));
  }, [ikApi, serviceId, environmentId, saved]);

  const suggestions = useMemo(() => {
    const byKey = new Map(templates.map((t) => [t.template, t]));
    return (spec?.claims ?? []).flatMap((claim) =>
      (byKey.get(claim.template)?.configuration?.binding_outputs ?? []).map(
        (output) => `\${${claim.alias}.outputs.${output}}`,
      ),
    );
  }, [spec, templates]);

  const keys = rows.map((r) => r.key);
  const keyError = (row: BindingSpec) => {
    if (!KEY_PATTERN.test(row.key))
      return "Letters, digits, _ . - ; must not start with a digit";
    if (keys.filter((k) => k === row.key).length > 1) return "Key used twice";
    return null;
  };
  const valueError = (row: BindingSpec) =>
    /\$\{[^}]*\}/.test(row.value.replace(REF, ""))
      ? "References look like ${alias.outputs.name}"
      : null;
  const dirty = JSON.stringify(rows) !== JSON.stringify(saved);
  const invalid = rows.some((r) => keyError(r) || valueError(r));

  const update = (index: number, patch: Partial<BindingSpec>) =>
    setRows((current) =>
      current.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    );

  const save = async () => {
    try {
      await ikApi.graphqlRequest(UPDATE_SERVICE_MUTATION, {
        id: serviceId,
        input: { spec: { claims: spec?.claims ?? [], bindings: rows } },
      });
      notify(
        "Bindings saved; reconcile each environment to deliver them",
        "success",
      );
      refreshEntity?.();
    } catch (error) {
      notifyError(error);
    }
  };

  const itemTable = (items: GqlBindingItem[], empty: string) =>
    items.length === 0 ? (
      <Typography variant="body2" color="text.secondary">
        {empty}
      </Typography>
    ) : (
      <Table size="small">
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.key}>
              <TableCell sx={{ fontFamily: "monospace", width: "30%" }}>
                {item.key}
              </TableCell>
              <TableCell sx={{ fontFamily: "monospace" }}>
                {item.value}
                {item.sensitive && (
                  <Chip size="small" label="sensitive" sx={{ ml: 1 }} />
                )}
              </TableCell>
              <TableCell sx={{ color: "text.secondary" }}>
                {item.sources.join(", ") || "literal"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );

  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 3, width: "100%" }}
    >
      <Box>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Bindings
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Keys delivered to the workload. <strong>Runtime</strong> keys are
          written to each environment&apos;s binding sink on reconcile;{" "}
          <strong>build</strong> keys are read by CI through{" "}
          <InlineCode>serviceBuildBindings</InlineCode>. Values may reference
          outputs of claims or referenced resources, e.g.{" "}
          <InlineCode>{"redis://${cache.outputs.host}:6379"}</InlineCode>.
        </Typography>
        {rows.length > 0 && (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Key</TableCell>
                <TableCell>Value</TableCell>
                <TableCell>Scope</TableCell>
                {canEdit && <TableCell />}
              </TableRow>
            </TableHead>
            <TableBody>
              {rows.map((row, index) => {
                const error = row.key ? keyError(row) : null;
                const refError = valueError(row);
                return (
                  <TableRow
                    key={index}
                    sx={{ "& > td": { verticalAlign: "top", py: 1 } }}
                  >
                    <TableCell sx={{ width: "25%" }}>
                      <TextField
                        size="small"
                        fullWidth
                        value={row.key}
                        disabled={!canEdit}
                        placeholder="KEY"
                        error={!!error}
                        helperText={error}
                        onChange={(e) => update(index, { key: e.target.value })}
                      />
                    </TableCell>
                    <TableCell>
                      <TextField
                        size="small"
                        fullWidth
                        value={row.value}
                        disabled={!canEdit}
                        error={!!refError}
                        helperText={refError}
                        onChange={(e) =>
                          update(index, { value: e.target.value })
                        }
                      />
                      {canEdit && suggestions.length > 0 && (
                        <Box
                          sx={{
                            display: "flex",
                            gap: 0.5,
                            flexWrap: "wrap",
                            mt: 0.75,
                          }}
                        >
                          {suggestions.map((s) => (
                            <Chip
                              key={s}
                              size="small"
                              variant="outlined"
                              label={s}
                              onClick={() =>
                                update(index, { value: row.value + s })
                              }
                            />
                          ))}
                        </Box>
                      )}
                    </TableCell>
                    <TableCell sx={{ width: 140 }}>
                      <TextField
                        select
                        size="small"
                        fullWidth
                        value={row.scope}
                        disabled={!canEdit}
                        onChange={(e) =>
                          update(index, {
                            scope: e.target.value as BindingSpec["scope"],
                          })
                        }
                      >
                        <MenuItem value="runtime">runtime</MenuItem>
                        <MenuItem value="build">build</MenuItem>
                      </TextField>
                    </TableCell>
                    {canEdit && (
                      <TableCell align="right">
                        <Tooltip title="Remove binding">
                          <IconButton
                            size="small"
                            sx={{ mt: 0.25 }}
                            aria-label={`Remove ${row.key || "binding"}`}
                            onClick={() =>
                              setRows((current) =>
                                current.filter((_, i) => i !== index),
                              )
                            }
                          >
                            <DeleteOutlineIcon fontSize="small" />
                          </IconButton>
                        </Tooltip>
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {rows.length === 0 && (
          <Typography variant="body2" sx={{ py: 1 }}>
            No bindings yet.
          </Typography>
        )}
        {canEdit && (
          <Box sx={{ display: "flex", gap: 1, mt: 1 }}>
            <Button
              startIcon={<AddIcon />}
              onClick={() =>
                setRows((current) => [
                  ...current,
                  { key: "", value: "", scope: "runtime" },
                ])
              }
            >
              Add binding
            </Button>
            <Button
              variant="contained"
              disabled={!dirty || invalid}
              onClick={save}
            >
              Save bindings
            </Button>
            {dirty && (
              <Button onClick={() => setRows(saved)} color="inherit">
                Discard
              </Button>
            )}
          </Box>
        )}
      </Box>

      <Card variant="outlined">
        <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <Box sx={{ display: "flex", gap: 2, alignItems: "center" }}>
            <Typography variant="subtitle1">Resolved in</Typography>
            <TextField
              select
              size="small"
              label="Environment"
              value={environmentId}
              onChange={(e) => setEnvironmentId(e.target.value)}
              sx={{ minWidth: 320 }}
            >
              {environments.map((e) => (
                <MenuItem key={e.id} value={e.id}>
                  {e.displayName || e.name}
                  {e.region ? ` · ${e.region}` : ""}
                </MenuItem>
              ))}
            </TextField>
          </Box>
          {loading && <CircularProgress size={24} />}
          {!loading && preview && (
            <>
              {!preview.deployed && (
                <Alert severity="info">
                  The service is not deployed here; only literal bindings can
                  resolve.
                </Alert>
              )}
              <Box sx={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                <Typography variant="body2">
                  Sink:{" "}
                  <strong>{SINK_LABELS[preview.sink] ?? preview.sink}</strong>
                </Typography>
                {preview.path && (
                  <Typography variant="body2">
                    Path: <InlineCode>{preview.path}</InlineCode>
                  </Typography>
                )}
                {preview.mountPath && (
                  <Typography variant="body2">
                    Pods read it at <InlineCode>{preview.mountPath}</InlineCode>{" "}
                    through SecretProviderClass{" "}
                    <InlineCode>{preview.secretProviderClass}</InlineCode>
                    {preview.manageSecretProviderClass
                      ? " (created by InfraKitchen if missing)"
                      : ""}
                  </Typography>
                )}
                {preview.sink === "kubernetes_secret" && (
                  <Typography variant="body2">
                    Namespace: <InlineCode>{preview.namespace}</InlineCode>
                  </Typography>
                )}
              </Box>
              {preview.errors.map((e) => (
                <Alert key={e} severity="warning">
                  {e}
                </Alert>
              ))}
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Runtime (values masked)
                </Typography>
                {itemTable(
                  preview.runtime,
                  "No runtime bindings resolve here.",
                )}
              </Box>
              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>
                  Build
                </Typography>
                {itemTable(preview.build, "No build bindings resolve here.")}
              </Box>
              <Typography variant="body2" color="text.secondary">
                {preview.appliedAt ? (
                  <>
                    Last delivered {preview.appliedKeys.length} keys to{" "}
                    <InlineCode>{preview.appliedPath}</InlineCode>{" "}
                    <RelativeTime date={preview.appliedAt} />
                  </>
                ) : (
                  "Not delivered yet; bindings are written when the environment is reconciled."
                )}
              </Typography>
            </>
          )}
        </CardContent>
      </Card>
    </Box>
  );
};
