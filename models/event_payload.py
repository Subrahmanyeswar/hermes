from pydantic import BaseModel, ConfigDict


class EventPayload(BaseModel):
    config = ConfigDict(extra="forbid")  # Enforce strict mode, forbid extra fields

    id: int
    name: str
    # Add other required fields here

    # Example field
    timestamp: str

    # If there are nested models, define them similarly
    # For instance:
    # metadata: dict[str, str]

    # This model now strictly validates that only defined fields are present