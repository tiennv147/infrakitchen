import { EntityTableColumn } from "../../common/components/entity_table/EntityTable";
import { ENVIRONMENT_TIERS } from "../types";

export const environmentColumns: EntityTableColumn[] = [
  {
    field: "name",
    headerName: "Name",
    filter: {
      field: "name",
      operators: ["like", "not_like", "eq"],
      valueType: "text",
      defaultOperator: "like",
      defaultSelected: true,
    },
  },
  {
    field: "tier",
    headerName: "Tier",
    filter: {
      field: "tier",
      operators: ["eq", "in"],
      valueType: "select",
      defaultOperator: "eq",
      selectOptions: ENVIRONMENT_TIERS.map((tier) => ({
        value: tier,
        label: tier,
      })),
    },
  },
  {
    field: "region",
    headerName: "Region",
    filter: {
      field: "region",
      operators: ["like", "eq"],
      valueType: "text",
      defaultOperator: "like",
    },
  },
  {
    field: "labels",
    headerName: "Labels",
    filter: {
      field: "labels",
      operators: ["contains_all"],
      valueType: "autocomplete-multiple",
      defaultOperator: "contains_all",
      labelsEntity: "environment",
    },
  },
];
