export interface TreeResponse {
  id: string;
  nodeId: string;
  name: string;
  state?: string;
  status: string;
  templateName?: string;
  // Set when a tree mixes entity types, e.g. services and resources.
  entityName?: string;
  relation?: string;
  children: TreeResponse[];
}
