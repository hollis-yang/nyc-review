from contextvars import ContextVar

request_authorization: ContextVar[str] = ContextVar("request_authorization", default="")
