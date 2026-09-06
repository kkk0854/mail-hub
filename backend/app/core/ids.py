import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:24]}"
