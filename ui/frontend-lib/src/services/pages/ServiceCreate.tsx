import { useCallback, useEffect, useMemo, useState } from "react";

import { Controller, useForm } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router";

import AddIcon from "@mui/icons-material/Add";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  IconButton,
  Step,
  StepLabel,
  Stepper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";

import { LabelInput, MultiSelectEditor } from "../../common";
import { PropertyCard } from "../../common/components/cards/PropertyCard";
import ReferenceInput from "../../common/components/inputs/ReferenceInput";
import { useConfig } from "../../common/context/ConfigContext";
import { notify, notifyError } from "../../common/hooks/useNotification";
import PageContainer from "../../common/PageContainer";
import { ENVIRONMENTS_SHORT_QUERY } from "../../environments/graphql";
import { GqlEnvironmentShort } from "../../environments/types";
import { IkEntity } from "../../types";
import { GqlUserShort, USERS_SHORT_QUERY } from "../../users/graphql";
import { ClaimEditorDialog } from "../components/ClaimEditorDialog";
import { PlanSummary } from "../components/ServicePlanDialog";
import {
  CLAIMABLE_TEMPLATES_QUERY,
  CREATE_SERVICE_INSTANCE_MUTATION,
  CREATE_SERVICE_MUTATION,
  GqlClaimableTemplate,
  GqlServicePlan,
  SERVICE_INSTANCE_ACTION_MUTATION,
  SERVICE_PLAN_QUERY,
} from "../graphql";
import { ClaimSpec, ServiceCreateRequest } from "../types";

type UserOption = GqlUserShort & { displayName?: string | null };

const getUserLabel = (user: UserOption) => user.displayName || user.identifier;

const STEPS = ["Basics", "Environments", "Dependencies", "Plan", "Apply"];
const TIER_ORDER: Record<string, number> = { dev: 0, staging: 1, prod: 2 };

interface Created {
  serviceId: string;
  instances: Record<string, string>;
  plans: Record<string, GqlServicePlan | null>;
}

export const ServiceCreatePage = () => {
  const { ikApi, linkPrefix } = useConfig();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const presetProjectId = searchParams.get("project_id");

  const {
    control,
    trigger,
    getValues,
    formState: { errors },
  } = useForm<ServiceCreateRequest>({
    defaultValues: {
      name: "",
      displayName: "",
      description: "",
      projectId: presetProjectId ?? "",
      repositoryUrl: "",
      labels: [],
      owners: [],
    },
    mode: "onChange",
  });

  const [buffer, setBuffer] = useState<Record<string, IkEntity | IkEntity[]>>(
    {},
  );
  const [users, setUsers] = useState<UserOption[]>([]);

  useEffect(() => {
    const loadUsers = async () => {
      try {
        const response = await ikApi.graphqlRequest<{ users: UserOption[] }>(
          USERS_SHORT_QUERY,
          {
            sort: ["identifier", "ASC"],
            range: [0, 999],
          },
        );
        setUsers(response.users || []);
      } catch (error: any) {
        notifyError(error);
      }
    };

    loadUsers();
  }, [ikApi]);

  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState(false);
  const [environments, setEnvironments] = useState<GqlEnvironmentShort[]>([]);
  const [selectedEnvs, setSelectedEnvs] = useState<string[]>([]);
  const [templates, setTemplates] = useState<GqlClaimableTemplate[]>([]);
  const [claims, setClaims] = useState<ClaimSpec[]>([]);
  const [editing, setEditing] = useState<ClaimSpec | null | undefined>(
    undefined,
  );
  const [created, setCreated] = useState<Created | null>(null);
  const [deployEnvs, setDeployEnvs] = useState<string[]>([]);

  useEffect(() => {
    Promise.all([
      ikApi.graphqlRequest<{ environments: GqlEnvironmentShort[] }>(
        ENVIRONMENTS_SHORT_QUERY,
        { sort: ["name", "ASC"], range: [0, 1000] },
      ),
      ikApi.graphqlRequest<{ claimableTemplates: GqlClaimableTemplate[] }>(
        CLAIMABLE_TEMPLATES_QUERY,
      ),
    ])
      .then(([e, t]) => {
        setEnvironments(
          (e.environments || [])
            .filter((env) => env.status?.toLowerCase() === "enabled")
            .sort(
              (a, b) =>
                (TIER_ORDER[a.tier] ?? 1) - (TIER_ORDER[b.tier] ?? 1) ||
                a.name.localeCompare(b.name),
            ),
        );
        setTemplates(t.claimableTemplates || []);
      })
      .catch(notifyError);
  }, [ikApi]);

  const envName = useMemo(
    () =>
      Object.fromEntries(
        environments.map((e) => [e.id, e.displayName || e.name]),
      ),
    [environments],
  );

  const toggle = (list: string[], id: string) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

  // Creating the service is the point of no return: the plan needs it to exist.
  const createAndPlan = useCallback(async () => {
    setBusy(true);
    try {
      const response = await ikApi.graphqlRequest<{
        createService: { id: string };
      }>(CREATE_SERVICE_MUTATION, {
        input: { ...getValues(), spec: { claims } },
      });
      const serviceId = response.createService.id;
      const instances: Record<string, string> = {};
      for (const environmentId of selectedEnvs) {
        const r = await ikApi.graphqlRequest<{
          createServiceInstance: { id: string };
        }>(CREATE_SERVICE_INSTANCE_MUTATION, {
          input: { serviceId, environmentId },
        });
        instances[environmentId] = r.createServiceInstance.id;
      }
      notify("Service created", "success");
      if (selectedEnvs.length === 0) {
        navigate(`${linkPrefix}services/${serviceId}`);
        return;
      }
      const plans: Record<string, GqlServicePlan | null> = {};
      for (const environmentId of selectedEnvs) {
        plans[environmentId] = await ikApi
          .graphqlRequest<{ servicePlan: GqlServicePlan }>(SERVICE_PLAN_QUERY, {
            serviceId,
            environmentId,
          })
          .then((r) => r.servicePlan)
          .catch((error) => {
            notifyError(error);
            return null;
          });
      }
      setCreated({ serviceId, instances, plans });
      setDeployEnvs(
        selectedEnvs.filter((id) => plans[id] && !plans[id]?.errors.length),
      );
      setStep(3);
    } catch (error: any) {
      notifyError(error);
    } finally {
      setBusy(false);
    }
  }, [ikApi, getValues, claims, selectedEnvs, navigate, linkPrefix]);

  const deploy = useCallback(async () => {
    if (!created) return;
    setBusy(true);
    try {
      for (const environmentId of deployEnvs) {
        await ikApi.graphqlRequest(SERVICE_INSTANCE_ACTION_MUTATION, {
          id: created.instances[environmentId],
          input: { action: "execute" },
        });
      }
      notify(
        deployEnvs.length
          ? `Deploying to ${deployEnvs.length} environment(s)`
          : "Service created without deploying",
        "success",
      );
      navigate(`${linkPrefix}services/${created.serviceId}/environments`);
    } catch (error: any) {
      notifyError(error);
    } finally {
      setBusy(false);
    }
  }, [created, deployEnvs, ikApi, navigate, linkPrefix]);

  const next = async () => {
    if (step === 0 && !(await trigger())) return;
    if (step === 2) {
      await createAndPlan();
      return;
    }
    if (step === 4) {
      await deploy();
      return;
    }
    setStep(step + 1);
  };

  const nextLabel =
    step === 2
      ? selectedEnvs.length
        ? "Create and plan"
        : "Create service"
      : step === 4
        ? deployEnvs.length
          ? "Deploy"
          : "Finish"
        : "Next";

  const templateName = (key: string) =>
    templates.find((t) => t.template === key)?.name ?? key;

  return (
    <PageContainer
      title="Create Service"
      bottomActions={
        <>
          <Button
            onClick={() =>
              created
                ? navigate(`${linkPrefix}services/${created.serviceId}`)
                : navigate(`${linkPrefix}services`)
            }
          >
            {created ? "Skip" : "Cancel"}
          </Button>
          <Button
            disabled={busy || step === 0 || step === 3}
            onClick={() => setStep(step - 1)}
          >
            Back
          </Button>
          <Button
            variant="contained"
            disabled={busy}
            onClick={next}
            startIcon={busy ? <CircularProgress size={16} /> : undefined}
          >
            {nextLabel}
          </Button>
        </>
      }
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          flexDirection: "column",
          width: "100%",
          minWidth: 320,
        }}
      >
        <Stepper activeStep={step} sx={{ width: "100%", mb: 3 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {step === 1 && (
          <PropertyCard title="Environments">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Where the service runs. You can add more later from its
              Environments tab.
            </Typography>
            <Table size="small">
              <TableBody>
                {environments.map((env) => (
                  <TableRow
                    key={env.id}
                    hover
                    onClick={() =>
                      setSelectedEnvs(toggle(selectedEnvs, env.id))
                    }
                    sx={{ cursor: "pointer" }}
                  >
                    <TableCell padding="checkbox">
                      <Checkbox
                        size="small"
                        checked={selectedEnvs.includes(env.id)}
                      />
                    </TableCell>
                    <TableCell>{env.displayName || env.name}</TableCell>
                    <TableCell>{env.tier}</TableCell>
                    <TableCell>{env.region}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            {environments.length === 0 && (
              <Alert severity="info">
                No enabled environments yet; the service can be created now and
                deployed later.
              </Alert>
            )}
          </PropertyCard>
        )}

        {step === 2 && (
          <PropertyCard title="Dependencies">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Infrastructure the service claims from the offering catalog, in
              every environment. Optional; it can be changed later.
            </Typography>
            {claims.length > 0 && (
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Alias</TableCell>
                    <TableCell>Offering</TableCell>
                    <TableCell />
                  </TableRow>
                </TableHead>
                <TableBody>
                  {claims.map((claim) => (
                    <TableRow key={claim.alias}>
                      <TableCell sx={{ fontFamily: "monospace" }}>
                        {claim.alias}
                      </TableCell>
                      <TableCell>{templateName(claim.template)}</TableCell>
                      <TableCell align="right">
                        <IconButton
                          size="small"
                          aria-label={`Edit ${claim.alias}`}
                          onClick={() => setEditing(claim)}
                        >
                          <EditOutlinedIcon fontSize="small" />
                        </IconButton>
                        <IconButton
                          size="small"
                          aria-label={`Remove ${claim.alias}`}
                          onClick={() =>
                            setClaims(
                              claims.filter((c) => c.alias !== claim.alias),
                            )
                          }
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            <Button
              size="small"
              variant="outlined"
              startIcon={<AddIcon />}
              sx={{ mt: 1 }}
              onClick={() => setEditing(null)}
            >
              Add dependency
            </Button>
            <ClaimEditorDialog
              open={editing !== undefined}
              claim={editing ?? null}
              claims={claims}
              templates={templates}
              onClose={() => setEditing(undefined)}
              onSave={(claim) => {
                setClaims((current) =>
                  editing
                    ? current.map((c) =>
                        c.alias === editing.alias ? claim : c,
                      )
                    : [...current, claim],
                );
                setEditing(undefined);
              }}
            />
          </PropertyCard>
        )}

        {step === 3 && created && (
          <Box sx={{ width: "100%" }}>
            <Alert severity="success" sx={{ mb: 2 }}>
              The service is created. Nothing has been provisioned yet; review
              what deploying would do in each environment.
            </Alert>
            {selectedEnvs.map((environmentId) => (
              <PropertyCard
                key={environmentId}
                title={envName[environmentId] ?? environmentId}
              >
                <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  {created.plans[environmentId] ? (
                    <PlanSummary plan={created.plans[environmentId]!} />
                  ) : (
                    <Alert severity="warning">
                      The plan could not be loaded.
                    </Alert>
                  )}
                </Box>
              </PropertyCard>
            ))}
          </Box>
        )}

        {step === 4 && created && (
          <PropertyCard title="Apply">
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
              Deploy now to the selected environments. Environments that require
              approval wait for it. Environments with plan errors are left out;
              fix the spec and deploy them from the service page.
            </Typography>
            <Table size="small">
              <TableBody>
                {selectedEnvs.map((environmentId) => {
                  const plan = created.plans[environmentId];
                  const blocked = !plan || plan.errors.length > 0;
                  return (
                    <TableRow key={environmentId}>
                      <TableCell padding="checkbox">
                        <Checkbox
                          size="small"
                          disabled={blocked}
                          checked={deployEnvs.includes(environmentId)}
                          onChange={() =>
                            setDeployEnvs(toggle(deployEnvs, environmentId))
                          }
                        />
                      </TableCell>
                      <TableCell>{envName[environmentId]}</TableCell>
                      <TableCell>
                        {blocked
                          ? "plan has errors"
                          : `${plan.creates} to create, ${plan.updates} to update`}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </PropertyCard>
        )}

        {step === 0 && (
          <>
            <PropertyCard title="Service Definition">
              <Box>
                <Controller
                  name="name"
                  control={control}
                  rules={{ required: "Name is required" }}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      label="Name"
                      required
                      variant="outlined"
                      error={!!errors.name}
                      helperText={
                        errors.name
                          ? errors.name.message
                          : "Unique within the project"
                      }
                      fullWidth
                      margin="normal"
                      slotProps={{
                        htmlInput: {
                          "aria-label": "Service name",
                        },
                      }}
                    />
                  )}
                />
                <Controller
                  name="displayName"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ""}
                      label="Display Name"
                      variant="outlined"
                      helperText="Optional human-friendly name"
                      fullWidth
                      margin="normal"
                      slotProps={{
                        htmlInput: {
                          "aria-label": "Service display name",
                        },
                      }}
                    />
                  )}
                />
                <Controller
                  name="description"
                  control={control}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      label="Description"
                      variant="outlined"
                      error={!!errors.description}
                      helperText={
                        errors.description
                          ? errors.description.message
                          : "Short summary of what this service does"
                      }
                      fullWidth
                      margin="normal"
                      slotProps={{
                        htmlInput: {
                          "aria-label": "Service description",
                        },
                      }}
                    />
                  )}
                />
                <Controller
                  name="projectId"
                  control={control}
                  rules={{ required: "Project is required" }}
                  render={({ field }) => (
                    <ReferenceInput
                      ikApi={ikApi}
                      buffer={buffer}
                      setBuffer={setBuffer}
                      {...field}
                      entity_name="projects"
                      showFields={["name"]}
                      error={!!errors.projectId}
                      helpertext={
                        errors.projectId
                          ? errors.projectId.message
                          : "The project this service belongs to"
                      }
                      value={field.value}
                      label="Select Project"
                    />
                  )}
                />
                <Controller
                  name="repositoryUrl"
                  control={control}
                  rules={{
                    pattern: {
                      value: /^https?:\/\/\S+$/,
                      message:
                        "Must be a URL starting with https:// or http://",
                    },
                  }}
                  render={({ field }) => (
                    <TextField
                      {...field}
                      value={field.value ?? ""}
                      label="Repository URL"
                      variant="outlined"
                      placeholder="https://github.com/org/repo"
                      error={!!errors.repositoryUrl}
                      helperText={
                        errors.repositoryUrl
                          ? errors.repositoryUrl.message
                          : "Where this service's source code lives"
                      }
                      fullWidth
                      margin="normal"
                      slotProps={{
                        htmlInput: {
                          "aria-label": "Service repository URL",
                        },
                      }}
                    />
                  )}
                />
                <Controller
                  name="labels"
                  control={control}
                  defaultValue={[]}
                  render={({ field }) => (
                    <LabelInput errors={errors} {...field} />
                  )}
                />
              </Box>
            </PropertyCard>

            <PropertyCard title="Service Owners">
              <Box>
                <Controller
                  name="owners"
                  control={control}
                  render={({ field }) => (
                    <MultiSelectEditor<UserOption>
                      value={users.filter((user) =>
                        field.value.includes(user.id),
                      )}
                      onChange={(value) =>
                        field.onChange(value.map((user) => user.id))
                      }
                      label="Assigned Users"
                      helperText="Users allowed to edit this service. Project owners can always edit it."
                      options={users}
                      getOptionLabel={getUserLabel}
                    />
                  )}
                />
              </Box>
            </PropertyCard>
          </>
        )}
      </Box>
    </PageContainer>
  );
};

ServiceCreatePage.path = "services/create";
