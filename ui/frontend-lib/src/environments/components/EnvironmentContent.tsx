import { Box } from "@mui/material";

import { Audit } from "../../common/components/activity/Audit";
import { DangerZoneCard } from "../../common/components/cards/DangerZoneCard";
import {
  TabbedContent,
  TabDefinition,
} from "../../common/components/cards/TabbedContent";
import { useEntityProvider } from "../../common/context/EntityContext";
import { Revision } from "../../revision/Revision";

import { EnvironmentOverview } from "./EnvironmentOverview";

export const EnvironmentContent = () => {
  const { entity, userEntityPermissions } = useEntityProvider();

  if (!entity) return null;

  const tabs: TabDefinition[] = [
    {
      label: "Audit",
      content: <Audit entityId={entity.id} />,
    },
    {
      label: "Revisions",
      content: <Revision resourceId={entity.id} resourceRevision={0} />,
    },
    {
      label: "Settings",
      content: <DangerZoneCard />,
      requiredPermission: `environment:${entity.id}`,
      permissionAction: "write",
    },
  ];

  return (
    <Box
      sx={{ display: "flex", flexDirection: "column", gap: 2, width: "100%" }}
    >
      <EnvironmentOverview environment={entity} />
      <TabbedContent
        tabs={tabs}
        userEntityPermissions={userEntityPermissions}
      />
    </Box>
  );
};
