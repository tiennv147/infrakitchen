import { useEffect, useState } from "react";

import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  IconButton,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";

import { CommonDialog } from "../../common/components/dialogs/CommonDialog";
import { useConfig } from "../../common/context/ConfigContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import {
  ADOPT_RESOURCES_MUTATION,
  AdoptResourceInput,
  RESOURCE_SEARCH_QUERY,
} from "../graphql";

const ALIAS_PATTERN = /^[a-z][a-z0-9_]{0,62}$/;

interface ResourceOption {
  id: string;
  name: string;
  state: string;
  template: { template: string } | null;
}

interface Row {
  resource: ResourceOption | null;
  alias: string;
  role: AdoptResourceInput["role"];
}

const emptyRow = (): Row => ({ resource: null, alias: "", role: "dependency" });

const suggestAlias = (resource: ResourceOption) =>
  (resource.template?.template || resource.name)
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, "_")
    .replace(/^[^a-z]+/, "")
    .slice(0, 63) || "resource";

interface AdoptResourcesDialogProps {
  open: boolean;
  serviceId: string;
  environmentId: string;
  environmentName: string;
  onClose: () => void;
  onAdopted: () => void;
}

export const AdoptResourcesDialog = ({
  open,
  serviceId,
  environmentId,
  environmentName,
  onClose,
  onAdopted,
}: AdoptResourcesDialogProps) => {
  const { ikApi } = useConfig();
  const [rows, setRows] = useState<Row[]>([emptyRow()]);
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<ResourceOption[]>([]);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (open) {
      setRows([emptyRow()]);
      setSubmitted(false);
    }
  }, [open]);

  useEffect(() => {
    if (!open || search.trim().length < 2) return;
    const handle = setTimeout(() => {
      ikApi
        .graphqlRequest<{ resources: ResourceOption[] }>(
          RESOURCE_SEARCH_QUERY,
          {
            filter: { name__like: search.trim() },
            range: [0, 25],
          },
        )
        .then((response) =>
          setOptions(
            (response.resources || []).filter(
              (r) => !["destroy", "destroyed"].includes(r.state.toLowerCase()),
            ),
          ),
        )
        .catch(notifyError);
    }, 250);
    return () => clearTimeout(handle);
  }, [ikApi, open, search]);

  const update = (index: number, patch: Partial<Row>) =>
    setRows((current) =>
      current.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    );

  const aliases = rows.map((r) => r.alias);
  const rowError = (row: Row) => {
    if (!row.resource) return "Pick a resource";
    if (!ALIAS_PATTERN.test(row.alias))
      return "Lowercase letters, digits and underscores";
    if (aliases.filter((a) => a === row.alias).length > 1)
      return "Alias used twice";
    return null;
  };

  const adopt = async () => {
    setSubmitted(true);
    if (rows.some((row) => rowError(row))) return;
    try {
      await ikApi.graphqlRequest(ADOPT_RESOURCES_MUTATION, {
        input: {
          serviceId,
          environmentId,
          resources: rows.map((row) => ({
            alias: row.alias,
            resourceId: row.resource!.id,
            role: row.role,
          })),
        },
      });
      notify("Resources adopted", "success");
      onAdopted();
    } catch (error) {
      notifyError(error);
    }
  };

  return (
    <CommonDialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      title={`Adopt existing resources · ${environmentName}`}
      content={
        <Box sx={{ display: "flex", flexDirection: "column", gap: 2, pt: 2 }}>
          <Alert severity="info">
            Adoption only links resources to the service; nothing is created,
            changed or destroyed. Owned resources are added to the service spec
            so the next plan here is a no-op. Use <strong>referenced</strong>{" "}
            for shared infrastructure the service must never destroy.
          </Alert>
          {rows.map((row, index) => {
            const error = submitted ? rowError(row) : null;
            return (
              <Box
                key={index}
                sx={{ display: "flex", gap: 1, alignItems: "flex-start" }}
              >
                <Autocomplete
                  sx={{ flex: 2 }}
                  options={options}
                  value={row.resource}
                  getOptionLabel={(option) => option.name}
                  isOptionEqualToValue={(a, b) => a.id === b.id}
                  onInputChange={(_, value) => setSearch(value)}
                  onChange={(_, resource) =>
                    update(index, {
                      resource,
                      alias:
                        row.alias || (resource ? suggestAlias(resource) : ""),
                    })
                  }
                  renderOption={(props, option) => (
                    <li {...props} key={option.id}>
                      <Box>
                        <Typography variant="body2">{option.name}</Typography>
                        <Typography variant="caption" color="text.secondary">
                          {option.template?.template} ·{" "}
                          {option.state.toLowerCase()}
                        </Typography>
                      </Box>
                    </li>
                  )}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Resource"
                      placeholder="Type at least 2 characters"
                      error={!!error && !row.resource}
                    />
                  )}
                />
                <TextField
                  sx={{ flex: 1 }}
                  label="Alias"
                  value={row.alias}
                  onChange={(event) =>
                    update(index, { alias: event.target.value })
                  }
                  error={!!error && !!row.resource}
                  helperText={error && row.resource ? error : " "}
                />
                <TextField
                  select
                  sx={{ width: 150 }}
                  label="Role"
                  value={row.role}
                  onChange={(event) =>
                    update(index, {
                      role: event.target.value as Row["role"],
                    })
                  }
                >
                  <MenuItem value="dependency">dependency</MenuItem>
                  <MenuItem value="workload">workload</MenuItem>
                  <MenuItem value="referenced">referenced</MenuItem>
                </TextField>
                <IconButton
                  sx={{ mt: 1 }}
                  aria-label="Remove row"
                  onClick={() =>
                    setRows((current) =>
                      current.length > 1
                        ? current.filter((_, i) => i !== index)
                        : [emptyRow()],
                    )
                  }
                >
                  <DeleteOutlineIcon />
                </IconButton>
              </Box>
            );
          })}
          <Box>
            <Button
              startIcon={<AddIcon />}
              onClick={() => setRows((current) => [...current, emptyRow()])}
            >
              Add resource
            </Button>
          </Box>
        </Box>
      }
      actions={
        <Button variant="contained" onClick={adopt}>
          Adopt
        </Button>
      }
    />
  );
};
