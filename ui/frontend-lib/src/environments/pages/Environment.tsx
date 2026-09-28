import { useParams } from "react-router";

import { EntityContainer } from "../../common/components/cards/EntityContainer";
import { EntityProvider } from "../../common/context/EntityContext";
import { EnvironmentContent } from "../components/EnvironmentContent";
import { ENVIRONMENT_DETAIL_FIELDS } from "../graphql";

export const EnvironmentPage = () => {
  const { environment_id } = useParams();

  return (
    <EntityProvider
      entity_name="environment"
      entity_id={environment_id || ""}
      entityFields={ENVIRONMENT_DETAIL_FIELDS}
    >
      <EntityContainer title="Environment Details">
        <EnvironmentContent />
      </EntityContainer>
    </EntityProvider>
  );
};

EnvironmentPage.path = "environments/:environment_id/:tab?";
