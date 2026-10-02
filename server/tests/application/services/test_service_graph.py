from uuid import uuid4

from application.services.graph import (
    MAX_DEPTH,
    GraphNode,
    LinkInfo,
    ServiceInfo,
    Topology,
    dependency_tree,
    dependents_tree,
    resource_impact_tree,
)


def _services(*names: str) -> dict[str, ServiceInfo]:
    return {name: ServiceInfo(id=uuid4(), name=name) for name in names}


def _topology(services: dict[str, ServiceInfo], edges: list[tuple[str, str]], links=()) -> Topology:
    depends_on: dict = {}
    dependents: dict = {}
    for service, dep in edges:
        depends_on.setdefault(services[service].id, []).append(services[dep].id)
        dependents.setdefault(services[dep].id, []).append(services[service].id)
    return Topology(
        services={s.id: s for s in services.values()},
        depends_on=depends_on,
        dependents=dependents,
        links=list(links),
    )


def _link(service: ServiceInfo, alias: str, role="dependency", env="shop-dev", resource_id=None) -> LinkInfo:
    return LinkInfo(
        service_id=service.id,
        environment_name=env,
        alias=alias,
        role=role,
        resource_id=resource_id or uuid4(),
        resource_name=f"{env}-{service.name}-{alias}",
        template="aws_redis",
        state="provisioned",
        status="done",
    )


def _names(node: GraphNode) -> list[str]:
    return [child.name for child in node.children]


def _all_node_ids(node: GraphNode) -> list[str]:
    return [node.node_id] + [i for child in node.children for i in _all_node_ids(child)]


class TestDependencyTree:
    def test_services_then_resources_with_owned_and_referenced(self):
        s = _services("checkout", "payments", "catalog")
        links = [
            _link(s["checkout"], "cache"),
            _link(s["checkout"], "events", role="referenced"),
            _link(s["payments"], "db"),
        ]
        tree = dependency_tree(
            _topology(s, [("checkout", "payments"), ("checkout", "catalog")], links), s["checkout"].id
        )

        assert (tree.entity_name, tree.relation) == ("service", "root")
        assert _names(tree) == ["catalog", "payments", "shop-dev-checkout-cache", "shop-dev-checkout-events"]
        assert [c.relation for c in tree.children] == ["depends_on", "depends_on", "owned", "referenced"]
        payments = tree.children[1]
        assert _names(payments) == ["shop-dev-payments-db"]
        assert tree.children[3].template_name == "aws_redis · events · referenced · shop-dev"

    def test_environment_filter(self):
        s = _services("checkout")
        links = [_link(s["checkout"], "cache", env="shop-dev"), _link(s["checkout"], "cache", env="shop-prod")]
        tree = dependency_tree(_topology(s, [], links), s["checkout"].id, environment_name="shop-prod")
        assert _names(tree) == ["shop-prod-checkout-cache"]

    def test_cycles_stop_and_are_labelled(self):
        s = _services("a", "b")
        tree = dependency_tree(_topology(s, [("a", "b"), ("b", "a")]), s["a"].id)
        b = tree.children[0]
        assert b.name == "b" and b.children[0].name == "a"
        assert b.children[0].template_name == "Depends on: cycle" and b.children[0].children == []

    def test_shared_dependency_gets_unique_node_ids(self):
        s = _services("app", "api", "worker", "db")
        tree = dependency_tree(
            _topology(s, [("app", "api"), ("app", "worker"), ("api", "db"), ("worker", "db")]), s["app"].id
        )
        ids = _all_node_ids(tree)
        assert len(ids) == len(set(ids)) == 5

    def test_depth_is_limited(self):
        names = [f"s{i}" for i in range(MAX_DEPTH + 3)]
        s = _services(*names)
        tree = dependency_tree(_topology(s, list(zip(names, names[1:], strict=False))), s["s0"].id)
        depth, node = 0, tree
        while node.children:
            node, depth = node.children[0], depth + 1
        assert depth == MAX_DEPTH


class TestImpact:
    def test_dependents_are_everything_a_change_can_break(self):
        s = _services("db-service", "api", "web", "admin")
        tree = dependents_tree(
            _topology(s, [("api", "db-service"), ("web", "api"), ("admin", "api")]), s["db-service"].id
        )
        assert _names(tree) == ["api"]
        assert _names(tree.children[0]) == ["admin", "web"]
        assert {c.relation for c in tree.children[0].children} == {"used_by"}

    def test_resource_impact_lists_owners_first_then_referencing_services_and_their_dependents(self):
        s = _services("orders", "search", "storefront")
        kafka = uuid4()
        links = [
            _link(s["search"], "events", role="referenced", resource_id=kafka),
            _link(s["orders"], "events", resource_id=kafka),
        ]
        topology = _topology(s, [("storefront", "search")], links)
        root = GraphNode(id=kafka, node_id=str(kafka), name="shared-kafka", entity_name="resource", relation="root")

        tree = resource_impact_tree(topology, root)

        assert _names(tree) == ["orders", "search"]
        assert tree.children[0].template_name == "Used by: owned as events in shop-dev"
        assert tree.children[1].template_name == "Used by: referenced as events in shop-dev"
        assert _names(tree.children[1]) == ["storefront"]
        ids = _all_node_ids(tree)
        assert len(ids) == len(set(ids))
