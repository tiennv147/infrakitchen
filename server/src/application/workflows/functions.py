from collections import defaultdict
from collections.abc import Hashable, Iterable

from core.constants.model import ModelActions, ModelStatus
from core.users.functions import user_api_permission
from core.users.model import UserDTO


def topological_levels[K: Hashable](nodes: list[K], edges: Iterable[tuple[K, K]]) -> list[tuple[K, int]]:
    """
    Kahn's algorithm with level tracking over (source, target) edges.
    Returns (node, level) in input order within each level; nodes at one level can run in parallel.
    Edges touching unknown nodes are ignored. Raises ValueError on a cycle.
    """
    node_set = set(nodes)
    graph: dict[K, set[K]] = defaultdict(set)
    in_degree: dict[K, int] = {node: 0 for node in nodes}

    for source, target in edges:
        if source in node_set and target in node_set and target not in graph[source]:
            graph[source].add(target)
            in_degree[target] += 1

    queue = [node for node in nodes if in_degree[node] == 0]
    result: list[tuple[K, int]] = []
    level = 0
    while queue:
        next_queue: list[K] = []
        for node in queue:
            result.append((node, level))
            for neighbor in graph.get(node, set()):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue
        level += 1

    if len(result) != len(nodes):
        raise ValueError("Circular dependency detected")
    return result


async def get_workflow_actions(requester: UserDTO, status: str) -> list[str]:
    apis = await user_api_permission(requester, "workflow")
    if not apis:
        return []
    requester_permissions = [apis.get("api:workflow", "")]

    actions: list[str] = []

    if "write" in requester_permissions or "admin" in requester_permissions:
        actions.append(ModelActions.EXECUTE)

    if status in (ModelStatus.PENDING, ModelStatus.ERROR):
        if "write" in requester_permissions or "admin" in requester_permissions:
            actions.append(ModelActions.EDIT)

    if "admin" in requester_permissions:
        actions.append(ModelActions.DELETE)

    return actions
