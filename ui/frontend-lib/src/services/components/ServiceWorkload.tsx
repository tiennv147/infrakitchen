import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  FormControlLabel,
  MenuItem,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";

import { CodeBlock } from "../../common/components/code/CodeBlock";
import { InlineCode } from "../../common/components/code/InlineCode";
import { RelativeTime } from "../../common/components/fields/RelativeTime";
import { useConfig } from "../../common/context/ConfigContext";
import { useEntityProvider } from "../../common/context/EntityContext";
import { useEventProvider } from "../../common/context/EventContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import {
  CREATE_SERVICE_DEPLOY_TOKEN_MUTATION,
  GqlDeployToken,
  GqlServiceDeployment,
  GqlServiceInstance,
  PROMOTE_WORKLOAD_MUTATION,
  ROLLBACK_WORKLOAD_MUTATION,
  SERVICE_DEPLOYMENTS_QUERY,
  SERVICE_INSTANCES_QUERY,
  SET_WORKLOAD_VERSION_MUTATION,
  UPDATE_SERVICE_MUTATION,
} from "../graphql";
import { ServiceSpec, WorkloadSpec } from "../types";

const TAG_PATTERN = /^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$/;
const TIER_ORDER: Record<string, number> = { dev: 0, staging: 1, prod: 2 };

const EMPTY_WORKLOAD: WorkloadSpec = {
  mode: "external",
  chart: "",
  chart_version: "",
  release_name: null,
  namespace: null,
  values_files: [],
  values_ref: "main",
  template: "helm_workload",
  source_code_version_id: null,
  image_tag_key: "image.tag",
  atomic: true,
  wait: true,
  timeout: 300,
  cleanup_on_fail: true,
};

const STATUS_COLOR: Record<
  string,
  "default" | "info" | "success" | "error" | "warning"
> = {
  waiting: "default",
  active: "info",
  done: "success",
  error: "error",
  cancelled: "warning",
  superseded: "default",
};

interface ServiceWorkloadProps {
  serviceId: string;
  serviceName: string;
  repositoryUrl: string | null;
  spec: ServiceSpec | null;
  canEdit: boolean;
}

const WorkloadDefinition = ({
  serviceId,
  serviceName,
  spec,
  canEdit,
}: Omit<ServiceWorkloadProps, "repositoryUrl">) => {
  const { ikApi } = useConfig();
  const { refreshEntity } = useEntityProvider();
  const saved = spec?.workload ?? null;
  const [form, setForm] = useState<WorkloadSpec>(saved ?? EMPTY_WORKLOAD);
  const [valuesText, setValuesText] = useState(
    (saved?.values_files ?? []).join("\n"),
  );

  useEffect(() => {
    setForm(saved ?? EMPTY_WORKLOAD);
    setValuesText((saved?.values_files ?? []).join("\n"));
  }, [saved]);

  const set = (patch: Partial<WorkloadSpec>) =>
    setForm((current) => ({ ...current, ...patch }));

  const next: WorkloadSpec = {
    ...form,
    release_name: form.release_name || null,
    namespace: form.namespace || null,
    values_files: valuesText
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean),
  };
  const dirty = JSON.stringify(next) !== JSON.stringify(saved);
  const invalid = !next.chart.trim() || !next.chart_version.trim();

  const save = async (workload: WorkloadSpec | null) => {
    try {
      await ikApi.graphqlRequest(UPDATE_SERVICE_MUTATION, {
        id: serviceId,
        input: { spec: { ...spec, claims: spec?.claims ?? [], workload } },
      });
      notify(workload ? "Workload saved" : "Workload removed", "success");
      refreshEntity?.();
    } catch (error) {
      notifyError(error);
    }
  };

  return (
    <Card variant="outlined">
      <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Box>
          <Typography variant="subtitle1">Workload</Typography>
          <Typography variant="body2" color="text.secondary">
            The Helm release that runs the service. <strong>External</strong>:
            recorded here, deployed by the service&apos;s own pipeline.{" "}
            <strong>Managed</strong>: InfraKitchen applies it after the
            service&apos;s infrastructure and bindings, and deploys versions
            through <InlineCode>setWorkloadVersion</InlineCode>.
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={form.mode}
          disabled={!canEdit}
          onChange={(_, mode) => mode && set({ mode })}
        >
          <ToggleButton value="external">External</ToggleButton>
          <ToggleButton value="managed">Managed</ToggleButton>
        </ToggleButtonGroup>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "2fr 1fr" },
            gap: 2,
          }}
        >
          <TextField
            size="small"
            label="Chart"
            placeholder="oci://registry.example.com/charts/app"
            value={form.chart}
            disabled={!canEdit}
            onChange={(e) => set({ chart: e.target.value })}
          />
          <TextField
            size="small"
            label="Chart version"
            value={form.chart_version}
            disabled={!canEdit}
            onChange={(e) => set({ chart_version: e.target.value })}
          />
          <TextField
            size="small"
            label="Release name"
            placeholder={serviceName}
            value={form.release_name ?? ""}
            disabled={!canEdit}
            onChange={(e) => set({ release_name: e.target.value })}
          />
          <TextField
            size="small"
            label="Namespace"
            placeholder={serviceName}
            value={form.namespace ?? ""}
            disabled={!canEdit}
            onChange={(e) => set({ namespace: e.target.value })}
          />
          <TextField
            size="small"
            label="Values files"
            multiline
            minRows={3}
            placeholder={
              "helm-values/values.yaml\nhelm-values/{environment}/values.yaml\nhelm-values/{region}/values.yaml?"
            }
            helperText="One path per line, applied in order. Placeholders: {service_name} {environment} {region} {tier}; a trailing ? makes a file optional."
            value={valuesText}
            disabled={!canEdit}
            onChange={(e) => setValuesText(e.target.value)}
          />
          <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <TextField
              size="small"
              label="Values ref"
              helperText="Branch or tag of the service repository"
              value={form.values_ref}
              disabled={!canEdit}
              onChange={(e) => set({ values_ref: e.target.value })}
            />
            <TextField
              size="small"
              label="Image tag value"
              helperText="Chart value set to the deployed version"
              value={form.image_tag_key}
              disabled={!canEdit}
              onChange={(e) => set({ image_tag_key: e.target.value })}
            />
          </Box>
        </Box>
        {form.mode === "managed" && (
          <Box
            sx={{
              display: "flex",
              gap: 2,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {(["atomic", "wait", "cleanup_on_fail"] as const).map((flag) => (
              <FormControlLabel
                key={flag}
                control={
                  <Switch
                    size="small"
                    checked={form[flag]}
                    disabled={!canEdit}
                    onChange={(e) => set({ [flag]: e.target.checked })}
                  />
                }
                label={flag.replace(/_/g, " ")}
              />
            ))}
            <TextField
              size="small"
              type="number"
              label="Timeout (s)"
              sx={{ width: 140 }}
              value={form.timeout}
              disabled={!canEdit}
              onChange={(e) => set({ timeout: Number(e.target.value) })}
            />
            <TextField
              size="small"
              label="Template"
              sx={{ width: 200 }}
              value={form.template}
              disabled={!canEdit}
              onChange={(e) => set({ template: e.target.value })}
            />
          </Box>
        )}
        {canEdit && (
          <Box sx={{ display: "flex", gap: 1 }}>
            <Button
              variant="contained"
              size="small"
              disabled={!dirty || invalid}
              onClick={() => save(next)}
            >
              Save workload
            </Button>
            {saved && (
              <Button
                size="small"
                color="inherit"
                variant="outlined"
                onClick={() => save(null)}
              >
                Remove
              </Button>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  );
};

const WorkloadDeployments = ({
  serviceId,
  canEdit,
}: {
  serviceId: string;
  canEdit: boolean;
}) => {
  const { ikApi } = useConfig();
  const { event } = useEventProvider();
  const [instances, setInstances] = useState<GqlServiceInstance[]>([]);
  const [history, setHistory] = useState<GqlServiceDeployment[]>([]);
  const [version, setVersion] = useState("");
  const [targets, setTargets] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [i, h] = await Promise.all([
        ikApi.graphqlRequest<{ serviceInstances: GqlServiceInstance[] }>(
          SERVICE_INSTANCES_QUERY,
          { filter: { service_id: [serviceId] }, range: [0, 1000] },
        ),
        ikApi.graphqlRequest<{ serviceDeployments: GqlServiceDeployment[] }>(
          SERVICE_DEPLOYMENTS_QUERY,
          { serviceId, limit: 50 },
        ),
      ]);
      setInstances(i.serviceInstances || []);
      setHistory(h.serviceDeployments || []);
    } catch (error) {
      notifyError(error);
    }
  }, [ikApi, serviceId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const ids = useMemo(() => new Set(instances.map((i) => i.id)), [instances]);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => {
    if (event?._entity_name === "service_instance" && ids.has(event.id)) {
      clearTimeout(timer.current);
      timer.current = setTimeout(fetchData, 300);
    }
  }, [event, ids, fetchData]);

  const sorted = useMemo(
    () =>
      [...instances].sort(
        (a, b) =>
          (TIER_ORDER[a.environment?.tier ?? ""] ?? 1) -
            (TIER_ORDER[b.environment?.tier ?? ""] ?? 1) ||
          (a.environment?.name ?? "").localeCompare(b.environment?.name ?? ""),
      ),
    [instances],
  );
  const lastTier = Math.max(
    ...sorted.map((i) => TIER_ORDER[i.environment?.tier ?? ""] ?? 1),
  );

  const run = async (request: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await request();
      notify(message, "success");
      await fetchData();
    } catch (error) {
      notifyError(error);
    } finally {
      setBusy(false);
    }
  };

  const deploy = () =>
    run(
      () =>
        ikApi.graphqlRequest(SET_WORKLOAD_VERSION_MUTATION, {
          input: {
            serviceId,
            version: version.trim(),
            environmentIds: targets.length ? targets : null,
          },
        }),
      `Rolling out ${version.trim()}`,
    );

  const toggle = (environmentId: string) =>
    setTargets((current) =>
      current.includes(environmentId)
        ? current.filter((id) => id !== environmentId)
        : [...current, environmentId],
    );

  return (
    <Card variant="outlined">
      <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Typography variant="subtitle1">Deploy</Typography>
        {sorted.length === 0 ? (
          <Alert severity="info">
            Deploy the service to an environment first (Environments tab).
          </Alert>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                {canEdit && <TableCell padding="checkbox" />}
                <TableCell>Environment</TableCell>
                <TableCell>Tier</TableCell>
                <TableCell>Running version</TableCell>
                <TableCell>Status</TableCell>
                {canEdit && <TableCell align="right" />}
              </TableRow>
            </TableHead>
            <TableBody>
              {sorted.map((instance) => {
                const env = instance.environment;
                const tier = TIER_ORDER[env?.tier ?? ""] ?? 1;
                return (
                  <TableRow key={instance.id}>
                    {canEdit && (
                      <TableCell padding="checkbox">
                        <Checkbox
                          size="small"
                          checked={!!env && targets.includes(env.id)}
                          onChange={() => env && toggle(env.id)}
                        />
                      </TableCell>
                    )}
                    <TableCell>{env?.displayName || env?.name}</TableCell>
                    <TableCell>{env?.tier}</TableCell>
                    <TableCell sx={{ fontFamily: "monospace" }}>
                      {instance.workloadVersion ?? "—"}
                    </TableCell>
                    <TableCell>
                      {instance.state.toLowerCase()} /{" "}
                      {instance.status.toLowerCase()}
                    </TableCell>
                    {canEdit && (
                      <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                        <Button
                          size="small"
                          disabled={busy || !env}
                          onClick={() =>
                            env &&
                            run(
                              () =>
                                ikApi.graphqlRequest(
                                  ROLLBACK_WORKLOAD_MUTATION,
                                  { serviceId, environmentId: env.id },
                                ),
                              `Rolling back ${env.name}`,
                            )
                          }
                        >
                          Roll back
                        </Button>
                        <Button
                          size="small"
                          disabled={
                            busy ||
                            !env ||
                            !instance.workloadVersion ||
                            tier >= lastTier
                          }
                          onClick={() =>
                            env &&
                            run(
                              () =>
                                ikApi.graphqlRequest(
                                  PROMOTE_WORKLOAD_MUTATION,
                                  { serviceId, environmentId: env.id },
                                ),
                              `Promoting ${instance.workloadVersion} to the next tier`,
                            )
                          }
                        >
                          Promote
                        </Button>
                      </TableCell>
                    )}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
        {canEdit && sorted.length > 0 && (
          <Box sx={{ display: "flex", gap: 1, alignItems: "flex-start" }}>
            <TextField
              size="small"
              label="Version (image tag)"
              value={version}
              error={!!version && !TAG_PATTERN.test(version.trim())}
              helperText={
                targets.length
                  ? `${targets.length} selected environment(s)`
                  : "All environments, dev → staging → prod"
              }
              onChange={(e) => setVersion(e.target.value)}
            />
            <Button
              variant="contained"
              size="small"
              sx={{ mt: 0.5 }}
              disabled={busy || !TAG_PATTERN.test(version.trim())}
              onClick={deploy}
            >
              Deploy
            </Button>
          </Box>
        )}
        <Typography variant="subtitle2" sx={{ mt: 1 }}>
          History
        </Typography>
        {history.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No deployments yet.
          </Typography>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>When</TableCell>
                <TableCell>Environment</TableCell>
                <TableCell>Version</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>By</TableCell>
                <TableCell>Note</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {history.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <RelativeTime date={d.createdAt} />
                  </TableCell>
                  <TableCell>{d.environmentName}</TableCell>
                  <TableCell sx={{ fontFamily: "monospace" }}>
                    {d.previousVersion ? `${d.previousVersion} → ` : ""}
                    {d.version}
                  </TableCell>
                  <TableCell>
                    <Chip
                      size="small"
                      label={d.status}
                      color={STATUS_COLOR[d.status]}
                    />
                  </TableCell>
                  <TableCell>{d.createdByName}</TableCell>
                  <TableCell sx={{ color: "text.secondary" }}>
                    {[d.source !== "api" ? d.source : "", d.message]
                      .filter(Boolean)
                      .join(": ")}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
};

const DeployAccess = ({
  serviceId,
  serviceName,
  repositoryUrl,
}: {
  serviceId: string;
  serviceName: string;
  repositoryUrl: string | null;
}) => {
  const { ikApi } = useConfig();
  const [name, setName] = useState(`${serviceName}-ci`);
  const [days, setDays] = useState(90);
  const [token, setToken] = useState<GqlDeployToken | null>(null);

  const create = async () => {
    try {
      const r = await ikApi.graphqlRequest<{
        createServiceDeployToken: GqlDeployToken;
      }>(CREATE_SERVICE_DEPLOY_TOKEN_MUTATION, {
        serviceId,
        name,
        expiresInDays: days,
      });
      setToken(r.createServiceDeployToken);
    } catch (error) {
      notifyError(error);
    }
  };

  const query = `mutation($v: String!) { setWorkloadVersion(input: {serviceId: \\"${serviceId}\\", version: $v}) { environmentName status } }`;
  const workflow = `permissions:
  id-token: write   # GitHub OIDC, no stored secret
steps:
  - name: Deploy with InfraKitchen
    env:
      VERSION: \${{ github.sha }}
    run: |
      TOKEN=$(curl -sH "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \\
        "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=infrakitchen" | jq -r .value)
      jq -n --arg v "$VERSION" '{query: "${query}", variables: {v: $v}}' |
        curl -sf -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
          --data @- "$INFRAKITCHEN_URL/api/graphql"`;

  return (
    <Card variant="outlined">
      <CardContent sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Typography variant="subtitle1">CI access</Typography>
        <Typography variant="body2" color="text.secondary">
          GitHub Actions in{" "}
          <InlineCode>{repositoryUrl || "the service repository"}</InlineCode>{" "}
          can deploy this service with its OIDC token when the{" "}
          <InlineCode>github_oidc</InlineCode> auth provider is enabled. Other
          CI systems use a deploy token that can only deploy this service.
        </Typography>
        <CodeBlock>{workflow}</CodeBlock>
        <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
          <TextField
            size="small"
            label="Token name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <TextField
            size="small"
            select
            label="Expires"
            sx={{ width: 140 }}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            {[30, 90, 180, 365].map((d) => (
              <MenuItem key={d} value={d}>
                {d} days
              </MenuItem>
            ))}
          </TextField>
          <Button
            variant="outlined"
            size="small"
            disabled={!name.trim()}
            onClick={create}
          >
            Create deploy token
          </Button>
        </Box>
        {token && (
          <Alert severity="warning" onClose={() => setToken(null)}>
            Copy the token now; it is not shown again.
            <CodeBlock sx={{ mt: 1 }}>{token.token}</CodeBlock>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
};

export const ServiceWorkload = (props: ServiceWorkloadProps) => {
  const managed = props.spec?.workload?.mode === "managed";
  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 3, width: "100%" }}
    >
      <WorkloadDefinition
        serviceId={props.serviceId}
        serviceName={props.serviceName}
        spec={props.spec}
        canEdit={props.canEdit}
      />
      {managed && (
        <WorkloadDeployments
          serviceId={props.serviceId}
          canEdit={props.canEdit}
        />
      )}
      {managed && props.canEdit && (
        <DeployAccess
          serviceId={props.serviceId}
          serviceName={props.serviceName}
          repositoryUrl={props.repositoryUrl}
        />
      )}
    </Box>
  );
};
