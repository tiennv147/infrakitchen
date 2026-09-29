import { useEffect, useMemo, useState } from "react";

import LinkIcon from "@mui/icons-material/Link";
import LinkOffIcon from "@mui/icons-material/LinkOff";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  IconButton,
  MenuItem,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";

import { CommonDialog } from "../../common/components/dialogs/CommonDialog";
import { useConfig } from "../../common/context/ConfigContext";
import { notifyError } from "../../common/hooks/useNotification";
import { ResourceVariableRow } from "../../resources/components/variables/ResourceVariablesForm";
import { RESOURCE_VARIABLE_SCHEMA_QUERY } from "../../resources/graphql";
import { ResourceVariableSchema } from "../../resources/types";
import { validateResourceVariableValue } from "../../resources/utils/validationRules";
import {
  GqlClaimableTemplate,
  GqlTemplateVersion,
  TEMPLATE_VERSIONS_QUERY,
} from "../graphql";
import { ClaimSpec } from "../types";

const ALIAS_PATTERN = /^[a-z][a-z0-9_]{0,62}$/;
const OUTPUT_REF =
  /^\$\{([a-z][a-z0-9_]*)\.outputs\.([A-Za-z_][A-Za-z0-9_]*)\}$/;

interface Wire {
  alias: string;
  output: string;
}

const parseWire = (value: unknown): Wire | null => {
  if (typeof value !== "string") return null;
  const match = OUTPUT_REF.exec(value.trim());
  return match ? { alias: match[1], output: match[2] } : null;
};

const isActiveVersion = (version: GqlTemplateVersion) =>
  version.lifecycleState.toLowerCase() === "active" &&
  version.status.toLowerCase() !== "disabled";

const versionLabel = (version: GqlTemplateVersion) =>
  version.sourceCodeVersion || version.sourceCodeBranch || version.identifier;

interface ClaimEditorDialogProps {
  open: boolean;
  claim: ClaimSpec | null;
  claims: ClaimSpec[];
  templates: GqlClaimableTemplate[];
  onClose: () => void;
  onSave: (claim: ClaimSpec) => void;
}

export const ClaimEditorDialog = ({
  open,
  claim,
  claims,
  templates,
  onClose,
  onSave,
}: ClaimEditorDialogProps) => {
  const { ikApi } = useConfig();
  const isNew = claim === null;

  const [alias, setAlias] = useState("");
  const [templateKey, setTemplateKey] = useState("");
  const [versionId, setVersionId] = useState("");
  const [parents, setParents] = useState<string[]>([]);
  const [values, setValues] = useState<Record<string, any>>({});
  const [versions, setVersions] = useState<GqlTemplateVersion[]>([]);
  const [schema, setSchema] = useState<ResourceVariableSchema[]>([]);
  const [schemaLoading, setSchemaLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setAlias(claim?.alias ?? "");
    setTemplateKey(claim?.template ?? "");
    setVersionId(claim?.source_code_version_id ?? "");
    setParents(claim?.parents ?? []);
    setValues(claim?.variables ?? {});
    setSubmitted(false);
  }, [open, claim]);

  const template = templates.find((t) => t.template === templateKey);
  const others = useMemo(
    () => claims.filter((c) => c.alias !== claim?.alias),
    [claims, claim],
  );

  const parentCandidates = useMemo(() => {
    if (!template) return [];
    const parentIds = new Set(template.parents.map((p) => p.id));
    const templateIdByKey = new Map(templates.map((t) => [t.template, t.id]));
    return others.filter((c) =>
      parentIds.has(templateIdByKey.get(c.template) ?? ""),
    );
  }, [template, templates, others]);

  useEffect(() => {
    if (!open || !template) {
      setVersions([]);
      return;
    }
    ikApi
      .graphqlRequest<{ sourceCodeVersions: GqlTemplateVersion[] }>(
        TEMPLATE_VERSIONS_QUERY,
        {
          filter: { template_id: [template.id] },
          sort: ["index", "DESC"],
          range: [0, 100],
        },
      )
      .then((response) => setVersions(response.sourceCodeVersions || []))
      .catch(notifyError);
  }, [ikApi, open, template]);

  const selectableVersions = useMemo(
    () =>
      versions.filter(
        (v) => v.status.toLowerCase() !== "disabled" || v.id === versionId,
      ),
    [versions, versionId],
  );
  const schemaVersionId = versionId || versions.find(isActiveVersion)?.id || "";

  useEffect(() => {
    if (!open || !schemaVersionId) {
      setSchema([]);
      return;
    }
    setSchemaLoading(true);
    ikApi
      .graphqlRequest<{ resourceVariableSchema: ResourceVariableSchema[] }>(
        RESOURCE_VARIABLE_SCHEMA_QUERY,
        { sourceCodeVersionId: schemaVersionId, parentResourceIds: [] },
      )
      .then((response) =>
        setSchema(
          (response.resourceVariableSchema || [])
            .filter((v) => !v.restricted && !v.sensitive)
            .map((v) => ({ ...v, description: v.description || "" })),
        ),
      )
      .catch(notifyError)
      .finally(() => setSchemaLoading(false));
  }, [ikApi, open, schemaVersionId]);

  const aliasError = !ALIAS_PATTERN.test(alias)
    ? "Lowercase letters, digits and underscores, starting with a letter"
    : isNew && claims.some((c) => c.alias === alias)
      ? "Alias already used by another claim"
      : null;

  const variableErrors = useMemo(() => {
    const errors: Record<string, string> = {};
    for (const variable of schema) {
      const value = values[variable.name] ?? variable.value;
      if (parseWire(value)) continue;
      const result = validateResourceVariableValue(value, variable);
      if (result !== true) errors[variable.name] = result;
    }
    return errors;
  }, [schema, values]);

  const setValue = (name: string, value: any) =>
    setValues((current) => ({ ...current, [name]: value }));

  const clearValue = (name: string) =>
    setValues((current) => {
      const { [name]: _removed, ...rest } = current;
      return rest;
    });

  const save = () => {
    setSubmitted(true);
    if (aliasError || !template || Object.keys(variableErrors).length > 0) {
      return;
    }
    const defaults = new Map(schema.map((v) => [v.name, v.value]));
    const variables = Object.fromEntries(
      Object.entries(values).filter(
        ([name, value]) =>
          value !== undefined &&
          value !== "" &&
          JSON.stringify(value) !== JSON.stringify(defaults.get(name)),
      ),
    );
    onSave({
      alias,
      template: template.template,
      source_code_version_id: versionId || null,
      variables,
      parents: parents.filter((p) =>
        parentCandidates.some((c) => c.alias === p),
      ),
    });
  };

  const renderWireEditor = (name: string, wire: Wire) => (
    <Box sx={{ display: "flex", gap: 1, width: "100%" }}>
      <TextField
        select
        size="small"
        label="Claim"
        value={wire.alias}
        onChange={(event) =>
          setValue(name, `\${${event.target.value}.outputs.${wire.output}}`)
        }
        sx={{ minWidth: 180 }}
      >
        {others.map((c) => (
          <MenuItem key={c.alias} value={c.alias}>
            {c.alias}
          </MenuItem>
        ))}
      </TextField>
      <TextField
        size="small"
        label="Output"
        value={wire.output}
        onChange={(event) =>
          setValue(name, `\${${wire.alias}.outputs.${event.target.value}}`)
        }
        fullWidth
      />
    </Box>
  );

  return (
    <CommonDialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      title={isNew ? "Add claim" : `Edit claim ${claim?.alias}`}
      content={
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 2 }}>
          <Box sx={{ display: "flex", gap: 2 }}>
            <TextField
              label="Alias"
              value={alias}
              onChange={(event) => setAlias(event.target.value)}
              disabled={!isNew}
              error={(submitted || alias !== "") && !!aliasError}
              helperText={
                (submitted || alias !== "") && aliasError
                  ? aliasError
                  : "How the service refers to this dependency, e.g. cache"
              }
              fullWidth
            />
            <TextField
              select
              label="Offering"
              value={templateKey}
              onChange={(event) => {
                setTemplateKey(event.target.value);
                setVersionId("");
                setParents([]);
                setValues({});
              }}
              disabled={!isNew}
              error={submitted && !template}
              helperText={template?.description || " "}
              fullWidth
            >
              {templates.map((t) => (
                <MenuItem key={t.id} value={t.template}>
                  {t.name}
                </MenuItem>
              ))}
            </TextField>
          </Box>

          {template && (
            <Box sx={{ display: "flex", gap: 2 }}>
              <TextField
                select
                label="Version"
                value={versionId}
                onChange={(event) => setVersionId(event.target.value)}
                helperText="Latest active is pinned on first apply"
                fullWidth
              >
                <MenuItem value="">Latest active</MenuItem>
                {selectableVersions.map((v) => (
                  <MenuItem key={v.id} value={v.id}>
                    {versionLabel(v)} · {v.lifecycleState.toLowerCase()}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Parents"
                value={parents}
                onChange={(event) =>
                  setParents(
                    typeof event.target.value === "string"
                      ? event.target.value.split(",")
                      : (event.target.value as string[]),
                  )
                }
                slotProps={{ select: { multiple: true } }}
                disabled={parentCandidates.length === 0}
                helperText={
                  parentCandidates.length === 0
                    ? "Parents come from the service anchor or the environment"
                    : "Claims this one is created under"
                }
                fullWidth
              >
                {parentCandidates.map((c) => (
                  <MenuItem key={c.alias} value={c.alias}>
                    {c.alias}
                  </MenuItem>
                ))}
              </TextField>
            </Box>
          )}

          {template && !schemaVersionId && versions.length > 0 && (
            <Alert severity="warning">
              This offering has no active version; pin a version to configure
              it.
            </Alert>
          )}
          {schemaLoading && (
            <Box sx={{ display: "flex", justifyContent: "center", py: 2 }}>
              <CircularProgress size={24} />
            </Box>
          )}
          {!schemaLoading && schema.length > 0 && (
            <Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Variables
              </Typography>
              {schema.map((variable) => {
                const value = values[variable.name] ?? variable.value ?? "";
                const wire = parseWire(value);
                const error = submitted ? variableErrors[variable.name] : null;
                return (
                  <Box
                    key={variable.name}
                    sx={{ display: "flex", alignItems: "flex-start", gap: 1 }}
                  >
                    <Box sx={{ flex: 1 }}>
                      <ResourceVariableRow
                        variable={variable}
                        field={{
                          name: variable.name,
                          value,
                          onChange: (next: any) =>
                            setValue(
                              variable.name,
                              next?.target ? next.target.value : next,
                            ),
                        }}
                        fieldState={
                          error ? { error: { message: error } } : undefined
                        }
                        hasDefault={
                          values[variable.name] === undefined &&
                          variable.value !== null
                        }
                      >
                        {wire
                          ? renderWireEditor(variable.name, wire)
                          : undefined}
                      </ResourceVariableRow>
                    </Box>
                    {others.length > 0 && (
                      <Tooltip
                        title={
                          wire
                            ? "Enter a value instead"
                            : "Wire from a claim output"
                        }
                      >
                        <IconButton
                          sx={{ mt: 2 }}
                          aria-label={
                            wire
                              ? `Unwire ${variable.name}`
                              : `Wire ${variable.name}`
                          }
                          onClick={() =>
                            wire
                              ? clearValue(variable.name)
                              : setValue(
                                  variable.name,
                                  `\${${others[0].alias}.outputs.${variable.name}}`,
                                )
                          }
                        >
                          {wire ? <LinkOffIcon /> : <LinkIcon />}
                        </IconButton>
                      </Tooltip>
                    )}
                  </Box>
                );
              })}
            </Box>
          )}
        </Box>
      }
      actions={
        <Button variant="contained" onClick={save}>
          {isNew ? "Add" : "Update"}
        </Button>
      }
    />
  );
};
