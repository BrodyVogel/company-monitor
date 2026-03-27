from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import init_db
from routers.api import router as api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Coverage Monitor", lifespan=lifespan)
app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
