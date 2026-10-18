from datetime import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models import TaskStatus, TaskType


class TaskCreate(BaseModel):
    type: TaskType = TaskType.task
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    datetime: Optional[dt] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    datetime: Optional[dt] = None
    status: Optional[TaskStatus] = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: TaskType
    title: str
    description: Optional[str]
    datetime: Optional[dt]
    status: TaskStatus
    created_at: dt