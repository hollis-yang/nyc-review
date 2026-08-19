from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.mcp.server import McpApiKeyMiddleware, bind_runtime, mcp, unbind_runtime
from app.runtime import AgentRuntime

settings = get_settings()


@asynccontextmanager
async def lifespan(application: FastAPI):
    runtime = await AgentRuntime.create(settings)
    application.state.agent_runtime = runtime
    bind_runtime(runtime)
    try:
        if settings.mcp_enabled:
            async with mcp.session_manager.run():
                yield
        else:
            yield
    finally:
        unbind_runtime()
        await runtime.close()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "adapter": settings.adapter,
        "rag": settings.rag_adapter,
        "model": settings.model_provider,
        "mcp": "enabled" if settings.mcp_enabled else "disabled",
    }


if settings.mcp_enabled:
    app.mount("/", McpApiKeyMiddleware(mcp.streamable_http_app(), settings.mcp_api_key))
