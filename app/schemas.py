from pydantic import BaseModel
from typing import Optional, List, Dict, Any

class AssignmentItem(BaseModel):
    assignment_id: int
    title: str
    due_date: Optional[str] = None
    link: str
    status: str  # "open" | "closed"

class ScanAssignmentsResponse(BaseModel):
    course: str
    count: int
    assignments: List[AssignmentItem]
    
class ReadAssignmentResponse(BaseModel):
    assignment_id: int
    title: str
    link: str
    due_date: Optional[str] = None
    status: Optional[str] = None  # "open" | "closed" (optional for this endpoint)
    submission_type: Optional[str] = None  # "file" | "text" | "both" | "unknown"
    instructions: str
    can_submit: Optional[bool] = None
    submission_status: Optional[str] = None
    
class DraftByIdRequest(BaseModel):
    assignment_id: int
       
class DraftRequest(BaseModel):
    assignment_title: str
    instructions: str
    due_date: Optional[str] = None
    submission_type: Optional[str] = None  # "file" | "text" | "both"
    extra: Dict[str, Any] = {}

class DraftResponse(BaseModel):
    action_plan: List[str]
    checklist: List[str]
    draft: str

class SubmissionRequest(BaseModel):
    assignment_id: int
    draft_content: str