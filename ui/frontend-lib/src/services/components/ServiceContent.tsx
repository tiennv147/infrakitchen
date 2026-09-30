import { useState } from "react";

import { Box } from "@mui/material";

import { Audit } from "../../common/components/activity/Audit";
import { DangerZoneCard } from "../../common/components/cards/DangerZoneCard";
import {
  TabbedContent,
  TabDefinition,
} from "../../common/components/cards/TabbedContent";
import { useEntityProvider } from "../../common/context/EntityContext";
import { Revision } from "../../revision/Revision";

import { ServiceBindings } from "./ServiceBindings";
import { ServiceDependencies } from "./ServiceDependencies";
import { ServiceEnvironments } from "./ServiceEnvironments";
import { ServiceNotificationSubscribersTable } from "./ServiceNotificationSubscribersTable";
import { ServiceOverview } from "./ServiceOverview";
import { ServicePermissions } from "./ServicePermissions";
import { ServiceWorkload } from "./ServiceWorkload";

export const ServiceContent = () => {
  const [subscribersRefreshKey, setSubscribersRefreshKey] = useState(0);
  const { entity, actions, userEntityPermissions } = useEntityProvider();

  if (!entity) return null;

  const tabs: TabDefinition[] = [
    {
      label: "Environments",
      content: (
        <ServiceEnvironments
          serviceId={entity.id}
          specRevision={entity.specRevision ?? 1}
          canEdit={actions.includes("edit")}
        />
      ),
    },
    {
      label: "Dependencies",
      content: (
        <ServiceDependencies
          serviceId={entity.id}
          spec={entity.spec ?? null}
          canEdit={actions.includes("edit")}
        />
      ),
    },
    {
      label: "Bindings",
      content: (
        <ServiceBindings
          serviceId={entity.id}
          spec={entity.spec ?? null}
          canEdit={actions.includes("edit")}
        />
      ),
    },
    {
      label: "Workload",
      content: (
        <ServiceWorkload
          serviceId={entity.id}
          serviceName={entity.name}
          repositoryUrl={entity.repositoryUrl ?? null}
          spec={entity.spec ?? null}
          canEdit={actions.includes("edit")}
        />
      ),
    },
    {
      label: "Policies",
      content: <ServicePermissions service={entity} />,
    },
    {
      label: "Notifications",
      content: (
        <ServiceNotificationSubscribersTable
          serviceId={entity.id}
          key={subscribersRefreshKey}
        />
      ),
    },
    {
      label: "Audit",
      content: <Audit entityId={entity.id} />,
    },
    {
      label: "Revisions",
      content: <Revision resourceId={entity.id} resourceRevision={0} />,
      requiredPermission: `service:${entity.id}`,
      permissionAction: "write",
    },
    {
      label: "Settings",
      content: <DangerZoneCard />,
      requiredPermission: `service:${entity.id}`,
      permissionAction: "write",
    },
  ];

  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}
    >
      <ServiceOverview
        service={entity}
        onSubscriptionChange={() =>
          setSubscribersRefreshKey((currentKey) => currentKey + 1)
        }
      />
      <TabbedContent
        tabs={tabs}
        userEntityPermissions={userEntityPermissions}
      />
    </Box>
  );
};
