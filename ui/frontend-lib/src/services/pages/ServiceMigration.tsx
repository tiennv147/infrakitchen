import { useCallback, useEffect, useMemo, useState } from "react";

import { useNavigate, useSearchParams } from "react-router";

import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
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

import { useConfig } from "../../common/context/ConfigContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import PageContainer from "../../common/PageContainer";
import {
  APPLY_SERVICE_MIGRATION_MUTATION,
  GqlMigrationProposal,
  GqlMigrationResource,
  SERVICE_MIGRATION_ANCHORS_QUERY,
  SERVICE_MIGRATION_PREVIEW_QUERY,
} from "../graphql";

const ALIAS_PATTERN = /^[a-z][a-z0-9_]{0,62}$/;

interface Row extends GqlMigrationResource {
  include: boolean;
}

type Draft = Record<string, Row[]>;

export const ServiceMigrationPage = () => {
  const { ikApi, linkPrefix } = useConfig();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const projectId = params.get("project_id");

  const [anchors, setAnchors] = useState<{ id: string; name: string }[]>([]);
  const [anchor, setAnchor] = useState<{ id: string; name: string } | null>(
    null,
  );
  const [proposal, setProposal] = useState<GqlMigrationProposal | null>(null);
  const [serviceName, setServiceName] = useState("");
  const [draft, setDraft] = useState<Draft>({});
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  useEffect(() => {
    ikApi
      .graphqlRequest<{
        serviceMigrationAnchors: { id: string; name: string }[];
      }>(SERVICE_MIGRATION_ANCHORS_QUERY, { projectId })
      .then((r) => setAnchors(r.serviceMigrationAnchors || []))
      .catch(notifyError);
  }, [ikApi, projectId]);

  const loadPreview = useCallback(
    async (anchorId: string) => {
      setLoading(true);
      setProposal(null);
      try {
        const { serviceMigrationPreview: p } = await ikApi.graphqlRequest<{
          serviceMigrationPreview: GqlMigrationProposal;
        }>(SERVICE_MIGRATION_PREVIEW_QUERY, { anchorResourceId: anchorId });
        setProposal(p);
        setServiceName(p.serviceName);
        setDraft(
          Object.fromEntries(
            p.environments.map((e) => [
              e.environmentId,
              e.resources.map((r) => ({
                ...r,
                include: !(r.ownedBy && r.role !== "referenced"),
              })),
            ]),
          ),
        );
      } catch (error) {
        notifyError(error);
      } finally {
        setLoading(false);
      }
    },
    [ikApi],
  );

  const update = (envId: string, index: number, patch: Partial<Row>) =>
    setDraft((current) => ({
      ...current,
      [envId]: current[envId].map((row, i) =>
        i === index ? { ...row, ...patch } : row,
      ),
    }));

  const problems = useMemo(() => {
    const found: string[] = [];
    for (const [envId, rows] of Object.entries(draft)) {
      const included = rows.filter((r) => r.include);
      const aliases = included.map((r) => r.alias);
      const env =
        proposal?.environments.find((e) => e.environmentId === envId)
          ?.environmentName ?? envId;
      for (const row of included) {
        if (!ALIAS_PATTERN.test(row.alias))
          found.push(`${env}: invalid alias '${row.alias}'`);
        if (aliases.filter((a) => a === row.alias).length > 1)
          found.push(`${env}: alias '${row.alias}' used twice`);
        if (row.ownedBy && row.role !== "referenced")
          found.push(
            `${env}: ${row.name} is owned by ${row.ownedBy}; reference it or leave it out`,
          );
      }
    }
    return [...new Set(found)];
  }, [draft, proposal]);

  const selectedCount = Object.values(draft)
    .flat()
    .filter((r) => r.include).length;

  const apply = async () => {
    if (!proposal || !proposal.projectId) return;
    setApplying(true);
    try {
      const result = await ikApi.graphqlRequest<{
        applyServiceMigration: { id: string };
      }>(APPLY_SERVICE_MIGRATION_MUTATION, {
        input: {
          anchorResourceId: proposal.anchorId,
          projectId: proposal.projectId,
          serviceName,
          environments: Object.entries(draft)
            .map(([environmentId, rows]) => ({
              environmentId,
              resources: rows
                .filter((r) => r.include)
                .map((r) => ({
                  alias: r.alias,
                  resourceId: r.resourceId,
                  role: r.role,
                })),
            }))
            .filter((e) => e.resources.length > 0),
        },
      });
      notify("Service created from existing resources", "success");
      navigate(`${linkPrefix}services/${result.applyServiceMigration.id}`);
    } catch (error) {
      notifyError(error);
    } finally {
      setApplying(false);
    }
  };

  return (
    <PageContainer title="Create services from existing resources">
      <Box
        sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}
      >
        <Typography variant="body2" color="text.secondary">
          Every <code>service</code> resource is an anchor for a Service. Review
          how its dependents map to environments and which are owned or only
          referenced, then apply. Applying adopts the resources: nothing is
          created, changed or destroyed.
        </Typography>
        <Autocomplete
          sx={{ maxWidth: 480 }}
          options={anchors}
          value={anchor}
          getOptionLabel={(option) => option.name}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          onChange={(_, value) => {
            setAnchor(value);
            if (value) loadPreview(value.id);
            else setProposal(null);
          }}
          renderInput={(p) => (
            <TextField {...p} label={`Service anchor (${anchors.length})`} />
          )}
        />

        {loading && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
            <CircularProgress />
          </Box>
        )}

        {proposal && !loading && (
          <>
            <TextField
              sx={{ maxWidth: 480 }}
              label="Service name"
              value={serviceName}
              onChange={(e) => setServiceName(e.target.value)}
              helperText={
                proposal.existingServiceId
                  ? "A service with this name exists; resources are added to it"
                  : "A new service is created in the anchor's project"
              }
            />
            {proposal.warnings.map((w) => (
              <Alert key={w} severity="warning">
                {w}
              </Alert>
            ))}
            {proposal.environments.map((env) => (
              <Card key={env.environmentId} variant="outlined">
                <CardContent>
                  <Typography variant="subtitle1" sx={{ mb: 1 }}>
                    {env.environmentName}
                  </Typography>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell padding="checkbox" />
                        <TableCell>Resource</TableCell>
                        <TableCell>Template</TableCell>
                        <TableCell>Alias</TableCell>
                        <TableCell>Role</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {(draft[env.environmentId] || []).map((row, index) => (
                        <TableRow key={row.resourceId}>
                          <TableCell padding="checkbox">
                            <Checkbox
                              checked={row.include}
                              onChange={(e) =>
                                update(env.environmentId, index, {
                                  include: e.target.checked,
                                })
                              }
                            />
                          </TableCell>
                          <TableCell>
                            <Typography variant="body2">{row.name}</Typography>
                            {row.state !== "provisioned" && (
                              <Chip
                                size="small"
                                label={row.state}
                                sx={{ mr: 1 }}
                              />
                            )}
                            {row.ownedBy && (
                              <Typography
                                variant="caption"
                                color="warning.main"
                              >
                                owned by {row.ownedBy}
                              </Typography>
                            )}
                          </TableCell>
                          <TableCell>{row.template}</TableCell>
                          <TableCell>
                            <TextField
                              size="small"
                              value={row.alias}
                              onChange={(e) =>
                                update(env.environmentId, index, {
                                  alias: e.target.value,
                                })
                              }
                            />
                          </TableCell>
                          <TableCell>
                            <TextField
                              select
                              size="small"
                              value={row.role}
                              onChange={(e) =>
                                update(env.environmentId, index, {
                                  role: e.target.value,
                                })
                              }
                            >
                              <MenuItem value="dependency">dependency</MenuItem>
                              <MenuItem value="workload">workload</MenuItem>
                              <MenuItem value="referenced">referenced</MenuItem>
                            </TextField>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </CardContent>
              </Card>
            ))}
            {proposal.unmatched.length > 0 && (
              <Alert severity="info">
                {proposal.unmatched.length} resources could not be matched to an
                environment by landing zone and are left out:{" "}
                {proposal.unmatched.map((u) => u.name).join(", ")}
              </Alert>
            )}
            {problems.map((p) => (
              <Alert key={p} severity="error">
                {p}
              </Alert>
            ))}
            <Box>
              <Button
                variant="contained"
                onClick={apply}
                disabled={
                  applying ||
                  problems.length > 0 ||
                  selectedCount === 0 ||
                  !serviceName ||
                  !proposal.projectId
                }
              >
                Adopt {selectedCount} resources into {serviceName || "service"}
              </Button>
            </Box>
          </>
        )}
      </Box>
    </PageContainer>
  );
};
