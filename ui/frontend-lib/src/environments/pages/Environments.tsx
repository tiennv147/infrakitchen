import { useCallback, useEffect, useState } from "react";

import { useNavigate } from "react-router";

import AddIcon from "@mui/icons-material/Add";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Typography,
} from "@mui/material";

import { FilterProvider, PermissionWrapper } from "../../common";
import { EntityCard } from "../../common/components/cards/EntityCard";
import { buildAdvancedApiFilters } from "../../common/components/filter_panel/buildAdvancedApiFilters";
import { FilterPanel } from "../../common/components/filter_panel/FilterPanel";
import { useConfig } from "../../common/context/ConfigContext";
import { notifyError } from "../../common/hooks/useNotification";
import PageContainer from "../../common/PageContainer";
import { environmentColumns } from "../components/environmentTableConfig";
import { ENVIRONMENTS_QUERY } from "../graphql";
import { GqlEnvironment } from "../types";

const entityName = "environment";

export const EnvironmentsPage = () => {
  const { ikApi, linkPrefix } = useConfig();
  const [environments, setEnvironments] = useState<GqlEnvironment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterValues, setFilterValues] = useState<Record<string, any>>({});
  const navigate = useNavigate();

  const fetchEnvironments = useCallback(async () => {
    const apiFilters = buildAdvancedApiFilters(filterValues);
    setError(null);
    try {
      const response = await ikApi.graphqlRequest<{
        environments: GqlEnvironment[];
      }>(ENVIRONMENTS_QUERY, {
        filter: Object.keys(apiFilters).length > 0 ? apiFilters : null,
        sort: ["name", "ASC"],
        range: [0, 1000],
      });
      setEnvironments(response.environments || []);
    } catch (error: any) {
      setError(error.message || "Failed to fetch environments");
      notifyError(error);
    } finally {
      setLoading(false);
    }
  }, [ikApi, filterValues]);

  useEffect(() => {
    fetchEnvironments();
  }, [fetchEnvironments]);

  const actions = (
    <PermissionWrapper
      requiredPermission="api:environment"
      permissionAction="admin"
    >
      <Button
        onClick={() => navigate(`${linkPrefix}environments/create`)}
        startIcon={<AddIcon />}
      >
        Create
      </Button>
    </PermissionWrapper>
  );

  const cardFields = (environment: GqlEnvironment) => (
    <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
      <Chip size="small" label={environment.tier} />
      {environment.region && (
        <Chip size="small" variant="outlined" label={environment.region} />
      )}
      {environment.status?.toLowerCase() === "disabled" && (
        <Chip size="small" color="warning" label="disabled" />
      )}
    </Box>
  );

  return (
    <PageContainer
      title="Environments"
      description="Deployment targets that services are deployed to. Each environment is one tier in one region or cluster."
      actions={actions}
    >
      <Box sx={{ width: "100%" }}>
        <FilterProvider
          columns={environmentColumns}
          storageKey={`filter_${entityName}s`}
          onFilterChange={setFilterValues}
          syncToUrl
        >
          <FilterPanel />
        </FilterProvider>
        {error ? (
          <Box sx={{ py: 4 }}>
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
            <Button onClick={fetchEnvironments}>Retry</Button>
          </Box>
        ) : loading ? (
          <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
            <CircularProgress />
          </Box>
        ) : environments.length === 0 ? (
          <Box sx={{ textAlign: "center", py: 4 }}>
            <Typography variant="h5" component="p">
              No environments match your filters
            </Typography>
          </Box>
        ) : (
          <Box
            sx={{
              "--card-min-width": { xs: "240px", sm: "260px", md: "300px" },
              display: "grid",
              gridTemplateColumns:
                "repeat(auto-fill, minmax(var(--card-min-width), 1fr))",
              gap: 2,
              width: "100%",
              mt: 3,
            }}
          >
            {environments.map((environment) => (
              <EntityCard
                key={environment.id}
                entity_name={entityName}
                name={environment.displayName || environment.name}
                description={environment.description ?? ""}
                detailsUrl={`${linkPrefix}environments/${environment.id}`}
                labels={environment.labels || []}
                lastUpdated={environment.updatedAt}
                entityFields={cardFields(environment)}
              />
            ))}
          </Box>
        )}
      </Box>
    </PageContainer>
  );
};

EnvironmentsPage.path = "environments";
