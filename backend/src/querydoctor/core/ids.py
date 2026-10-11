import uuid


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:24]}"
