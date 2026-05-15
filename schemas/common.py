from pydantic import BaseModel
from typing import Generic, TypeVar, Optional

T = TypeVar("T")

class ResponseModel(BaseModel, Generic[T]):
    code: int = 200
    message: str = "success"
    data: Optional[T] = None

class ListData(BaseModel, Generic[T]):
    total: int
    items: list[T]
    page: int = 1
    page_size: int = 20
