import { useCallback, useEffect, useMemo, useState } from "react";

import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import PlaylistPlayIcon from "@mui/icons-material/PlaylistPlay";
import {
  Box,
  Button,
  Chip,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";

import { useConfig } from "../../common/context/ConfigContext";
import { useEntityProvider } from "../../common/context/EntityContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import {
  CLAIMABLE_TEMPLATES_QUERY,
  GqlClaimableTemplate,
  UPDATE_SERVICE_MUTATION,
} from "../graphql";
import { ClaimSpec, ServiceSpec } from "../types";

import { ClaimEditorDialog } from "./ClaimEditorDialog";
import { ServicePlanDialog } from "./ServicePlanDialog";

const WIRE = /^\$\{([a-z][a-z0-9_]*)\.outputs\.[A-Za-z_][A-Za-z0-9_]*\}$/;

interface ServiceDependenciesProps {
  serviceId: string;
  spec: ServiceSpec | null;
  canEdit: boolean;
}

export const ServiceDependencies = ({
  serviceId,
  spec,
  canEdit,
}: ServiceDependenciesProps) => {
  const { ikApi, globalConfig } = useConfig();
  const { refreshEntity } = useEntityProvider();
  const [templates, setTemplates] = useState<GqlClaimableTemplate[]>([]);
  const [editing, setEditing] = useState<ClaimSpec | null | undefined>(
    undefined,
  );
  const [planOpen, setPlanOpen] = useState(false);

  const claims = useMemo(() => spec?.claims ?? [], [spec]);
  const offeringRequestUrl: string | null =
    globalConfig?.offering_request_url || null;

  useEffect(() => {
    ikApi
      .graphqlRequest<{ claimableTemplates: GqlClaimableTemplate[] }>(
        CLAIMABLE_TEMPLATES_QUERY,
      )
      .then((response) => setTemplates(response.claimableTemplates || []))
      .catch(notifyError);
  }, [ikApi]);

  const templateName = useCallback(
    (key: string) => templates.find((t) => t.template === key)?.name ?? key,
    [templates],
  );
  const inCatalog = (claim: ClaimSpec) =>
    templates.some((t) => t.template === claim.template);

  const saveClaims = async (next: ClaimSpec[], message: string) => {
    try {
      await ikApi.graphqlRequest(UPDATE_SERVICE_MUTATION, {
        id: serviceId,
        input: { spec: { claims: next } },
      });
      notify(message, "success");
      setEditing(undefined);
      refreshEntity?.();
    } catch (error) {
      notifyError(error);
    }
  };

  const upsertClaim = (claim: ClaimSpec) => {
    const exists = claims.some((c) => c.alias === claim.alias);
    const next = exists
      ? claims.map((c) => (c.alias === claim.alias ? claim : c))
      : [...claims, claim];
    saveClaims(next, exists ? "Claim updated" : "Claim added");
  };

  const removeClaim = (alias: string) => {
    const usedBy = claims.filter(
      (c) =>
        c.parents.includes(alias) ||
        Object.values(c.variables).some(
          (v) => typeof v === "string" && WIRE.exec(v)?.[1] === alias,
        ),
    );
    if (usedBy.length > 0) {
      notifyError(
        new Error(
          `'${alias}' is used by ${usedBy.map((c) => c.alias).join(", ")}; remove those references first`,
        ),
      );
      return;
    }
    saveClaims(
      claims.filter((c) => c.alias !== alias),
      "Claim removed",
    );
  };

  const wiredFrom = (claim: ClaimSpec) =>
    Object.values(claim.variables)
      .map((v) => (typeof v === "string" ? WIRE.exec(v)?.[1] : undefined))
      .filter((alias): alias is string => !!alias);

  return (
    <Box sx={{ width: "100%" }}>
      <Box sx={{ display: "flex", gap: 1, alignItems: "center", mb: 2 }}>
        {canEdit && (
          <Button
            startIcon={<AddIcon />}
            onClick={() => setEditing(null)}
            disabled={templates.length === 0}
          >
            Add claim
          </Button>
        )}
        <Button
          startIcon={<PlaylistPlayIcon />}
          onClick={() => setPlanOpen(true)}
        >
          Preview plan
        </Button>
        <Box sx={{ flex: 1 }} />
        {offeringRequestUrl && (
          <Button
            endIcon={<OpenInNewIcon />}
            href={offeringRequestUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            Request an offering
          </Button>
        )}
      </Box>

      {canEdit && templates.length === 0 && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          No offerings are published yet. Platform admins publish a template by
          marking it claimable on its Template page.
        </Typography>
      )}

      {claims.length === 0 ? (
        <Box sx={{ textAlign: "center", py: 4 }}>
          <Typography variant="h6" component="p">
            This service does not claim any infrastructure yet
          </Typography>
        </Box>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Alias</TableCell>
              <TableCell>Offering</TableCell>
              <TableCell>Version</TableCell>
              <TableCell>Depends on</TableCell>
              <TableCell>Variables</TableCell>
              {canEdit && <TableCell />}
            </TableRow>
          </TableHead>
          <TableBody>
            {claims.map((claim) => {
              const dependsOn = [
                ...new Set([...claim.parents, ...wiredFrom(claim)]),
              ];
              return (
                <TableRow key={claim.alias}>
                  <TableCell sx={{ fontFamily: "monospace" }}>
                    {claim.alias}
                    {claim.adopted && (
                      <Tooltip title="Reverse-compiled from an adopted resource">
                        <Chip size="small" label="adopted" sx={{ ml: 1 }} />
                      </Tooltip>
                    )}
                  </TableCell>
                  <TableCell>{templateName(claim.template)}</TableCell>
                  <TableCell>
                    {claim.source_code_version_id ? (
                      <Chip size="small" label="pinned" />
                    ) : (
                      <Chip size="small" variant="outlined" label="latest" />
                    )}
                  </TableCell>
                  <TableCell>
                    {dependsOn.length ? dependsOn.join(", ") : "—"}
                  </TableCell>
                  <TableCell>{Object.keys(claim.variables).length}</TableCell>
                  {canEdit && (
                    <TableCell align="right" sx={{ whiteSpace: "nowrap" }}>
                      <Tooltip
                        title={
                          inCatalog(claim)
                            ? "Edit claim"
                            : "Adopted from a template outside the catalog; change the resource instead"
                        }
                      >
                        <span>
                          <IconButton
                            size="small"
                            aria-label={`Edit ${claim.alias}`}
                            onClick={() => setEditing(claim)}
                            disabled={!inCatalog(claim)}
                          >
                            <EditOutlinedIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                      <Tooltip title="Remove claim">
                        <IconButton
                          size="small"
                          aria-label={`Remove ${claim.alias}`}
                          onClick={() => removeClaim(claim.alias)}
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

      <ClaimEditorDialog
        open={editing !== undefined}
        claim={editing ?? null}
        claims={claims}
        templates={templates}
        onClose={() => setEditing(undefined)}
        onSave={upsertClaim}
      />
      <ServicePlanDialog
        open={planOpen}
        serviceId={serviceId}
        onClose={() => setPlanOpen(false)}
      />
    </Box>
  );
};
