from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from Backend.database import get_db
from Backend.models import InventoryItem, User
from Backend.security import get_current_user
from Backend.schemas import (
    InventoryItemCreate,
    InventoryItemList,
    InventoryItemRead,
    InventoryItemUpdate,
    RuleBasedRecommendation,
)
from Backend.services.inventory_service import inventory_status_for, recommendation_for

router = APIRouter(prefix="/inventory", tags=["inventory management"])


def _find_item(db: Session, item_id: int, user: User) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Inventory item was not found.")
    if item.source_type == "manual" and item.owner_id != user.id:
        raise HTTPException(status_code=403, detail="This inventory item belongs to another user.")
    return item


def _require_manual_item(item: InventoryItem, user: User) -> None:
    if item.source_type != "manual":
        raise HTTPException(
            status_code=409,
            detail="Imported CSV snapshot records are read-only; add a live inventory item to edit stock.",
        )
    if item.owner_id != user.id:
        raise HTTPException(status_code=403, detail="This inventory item belongs to another user.")


@router.get("/items", response_model=InventoryItemList)
def list_inventory_items(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InventoryItemList:
    ownership = or_(
        InventoryItem.source_type == "csv_snapshot",
        InventoryItem.owner_id == user.id,
    )
    statement = select(InventoryItem).where(ownership)
    count_statement = (
        select(func.count()).select_from(InventoryItem).where(ownership)
    )
    if search:
        term = f"%{search.strip()}%"
        predicate = or_(
            InventoryItem.product_name.ilike(term),
            InventoryItem.category.ilike(term),
        )
        statement = statement.where(predicate)
        count_statement = count_statement.where(predicate)

    total = db.scalar(count_statement) or 0
    items = list(
        db.scalars(
            statement.order_by(InventoryItem.id.desc()).offset(offset).limit(limit)
        )
    )
    for item in items:
        item.inventory_status = inventory_status_for(item)
    if items:
        db.commit()

    return InventoryItemList(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/items",
    response_model=InventoryItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_inventory_item(
    payload: InventoryItemCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InventoryItem:
    item = InventoryItem(
        **payload.model_dump(),
        inventory_status="in_stock",
        source_type="manual",
        owner_id=user.id,
    )
    item.inventory_status = inventory_status_for(item)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/items/{item_id}", response_model=InventoryItemRead)
def get_inventory_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InventoryItem:
    item = _find_item(db, item_id, user)
    item.inventory_status = inventory_status_for(item)
    db.commit()
    return item


@router.put("/items/{item_id}", response_model=InventoryItemRead)
def update_inventory_item(
    item_id: int,
    payload: InventoryItemUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InventoryItem:
    item = _find_item(db, item_id, user)
    _require_manual_item(item, user)
    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    item.inventory_status = inventory_status_for(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory_item(
    item_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    item = _find_item(db, item_id, user)
    _require_manual_item(item, user)
    db.delete(item)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/recommendations", response_model=list[RuleBasedRecommendation]
)
def list_rule_based_recommendations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[RuleBasedRecommendation]:
    items = db.scalars(
        select(InventoryItem)
        .where(
            InventoryItem.source_type == "manual",
            InventoryItem.owner_id == user.id,
        )
        .order_by(InventoryItem.expiry_date, InventoryItem.id)
    )
    return [recommendation_for(item, date.today()) for item in items]
