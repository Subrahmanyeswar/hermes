import json
from fastapi import APIRouter, Query
from typing import List, Dict

# Mock data for demonstration
users_data = [{"id": i, "name": f"User {i}"} for i in range(1000)]  # large list for pagination

router = APIRouter()

@router.get("/users")
async def list_users(limit: int = Query(20, description="Number of users per page", ge=1, le=100),
                    offset: int = Query(0, description="Offset for pagination")):
    """
    List users with pagination.
    Query parameters: limit (default 20, max 100), offset (default 0).
    Returns paginated users, total count, and pagination metadata.
    """
    # Paginate the users
    paginated_users = users_data[offset:offset+limit]
    total = len(users_data)
    return {
        "users": paginated_users,
        "total": total,
        "page": offset // limit + 1 if limit > 0 else 0,
        "limit": limit,
        "offset": offset
    }