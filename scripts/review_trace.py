"""Reproduce the introduction authorization issue without changing seed data.

Run with: DATABASE_URL=sqlite:// .venv/bin/python -m scripts.review_trace
"""

import json
import asyncio

import httpx
import fastapi.dependencies.utils
import fastapi.routing
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, Club, Member, MemberAttribute


def main() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        db.add_all([Club(id="riverside", name="Riverside"), Club(id="oakhurst", name="Oakhurst")])
        db.flush()
        caller = Member(
            club_id="riverside", name="Caller", email="caller@example.test",
            token="riverside-member-1", role="member",
        )
        other = Member(
            club_id="oakhurst", name="Other", email="other@example.test",
            token="oakhurst-member-1", role="member",
        )
        db.add_all([caller, other])
        db.flush()
        db.add(MemberAttribute(
            member_id=other.id, club_id="oakhurst", kind="context",
            text="recently diagnosed with a chronic condition", confidence=0.9,
            restricted=True,
        ))
        db.commit()
        caller_id = caller.id
        other_id = other.id

    async def test_db():
        with Session(engine) as db:
            yield db

    # This environment cannot schedule AnyIO worker threads. Execute the same
    # synchronous route/dependency callables in the ASGI event loop for this trace.
    async def direct_call(func, *args, **kwargs):
        return func(*args, **kwargs)

    original_route_runner = fastapi.routing.run_in_threadpool
    original_dependency_runner = fastapi.dependencies.utils.run_in_threadpool
    fastapi.routing.run_in_threadpool = direct_call
    fastapi.dependencies.utils.run_in_threadpool = direct_call

    app.dependency_overrides[get_db] = test_db
    try:
        path = f"/introductions/{caller_id}/{other_id}?reason=business"
        async def request():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                return await client.get(path, headers={"X-Member-Token": "riverside-member-1"})

        response = asyncio.run(request())
        print(f"GET {path}")
        print("X-Member-Token: riverside-member-1")
        print(f"HTTP {response.status_code}")
        print(json.dumps(response.json(), ensure_ascii=False))
    finally:
        app.dependency_overrides.clear()
        fastapi.routing.run_in_threadpool = original_route_runner
        fastapi.dependencies.utils.run_in_threadpool = original_dependency_runner
        engine.dispose()


if __name__ == "__main__":
    main()
