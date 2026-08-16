from __future__ import annotations

from fastapi import HTTPException, status

from app.models.enums import ImageWorkflowStatus
from app.models.generation import ImageWorkflow
from app.schemas.generation import ImageWorkflowTransition


USER_TRANSITIONS: dict[ImageWorkflowStatus, set[ImageWorkflowStatus]] = {
    ImageWorkflowStatus.DRAFT: {ImageWorkflowStatus.PRODUCT_TYPE_READY},
    ImageWorkflowStatus.PRODUCT_TYPE_READY: {ImageWorkflowStatus.SCENE_PLAN_READY},
    ImageWorkflowStatus.SCENE_PLAN_READY: {ImageWorkflowStatus.HERO_SCENE_SELECTED},
    ImageWorkflowStatus.HERO_SCENE_SELECTED: {ImageWorkflowStatus.PROMPT_READY},
}


def apply_workflow_transition(
    workflow: ImageWorkflow, payload: ImageWorkflowTransition
) -> None:
    if workflow.status != payload.expected_status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow state changed; current state is {workflow.status.value}",
        )
    if workflow.revision != payload.expected_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow revision changed; current revision is {workflow.revision}",
        )
    if payload.target_status not in USER_TRANSITIONS.get(workflow.status, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Transition {workflow.status.value} -> {payload.target_status.value} is not allowed",
        )

    if payload.target_status == ImageWorkflowStatus.PRODUCT_TYPE_READY:
        if not payload.product_type:
            raise HTTPException(status_code=422, detail="product_type is required")
        workflow.product_type_json = payload.product_type
    elif payload.target_status == ImageWorkflowStatus.SCENE_PLAN_READY:
        if not payload.scene_plan:
            raise HTTPException(status_code=422, detail="scene_plan is required")
        workflow.scene_plan_json = payload.scene_plan
    elif payload.target_status == ImageWorkflowStatus.HERO_SCENE_SELECTED:
        if not payload.selected_scene:
            raise HTTPException(status_code=422, detail="selected_scene is required")
        workflow.selected_scene_json = payload.selected_scene
    elif payload.target_status == ImageWorkflowStatus.PROMPT_READY:
        if not payload.approved_prompt:
            raise HTTPException(status_code=422, detail="approved_prompt is required")
        workflow.approved_prompt = payload.approved_prompt

    workflow.status = payload.target_status
    workflow.revision += 1
