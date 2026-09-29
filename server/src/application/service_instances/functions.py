from core.constants.model import ModelActions, ModelState, ModelStatus


def get_service_instance_actions(
    *, can_edit: bool, state: ModelState | str, status: ModelStatus | str, owns_resources: bool
) -> list[str]:
    """Lifecycle actions for one service instance; the plan (dry run) is available to every reader."""
    state = ModelState(str(state).lower())
    status = ModelStatus(str(status).lower())
    if not can_edit or status in (ModelStatus.QUEUED, ModelStatus.IN_PROGRESS):
        return [ModelActions.DRYRUN]
    if status == ModelStatus.APPROVAL_PENDING:
        return [ModelActions.APPROVE, ModelActions.REJECT, ModelActions.DRYRUN]
    if state == ModelState.DESTROY:
        return [ModelActions.RETRY, ModelActions.DRYRUN] if status == ModelStatus.ERROR else [ModelActions.DRYRUN]
    if state == ModelState.DESTROYED:
        return [ModelActions.EXECUTE, ModelActions.DRYRUN, ModelActions.DELETE]

    actions: list[str] = []
    if status == ModelStatus.ERROR:
        actions.append(ModelActions.RETRY)
    actions += [ModelActions.EXECUTE, ModelActions.DRYRUN, ModelActions.ADOPT]
    actions.append(ModelActions.DESTROY if owns_resources else ModelActions.DELETE)
    return actions
