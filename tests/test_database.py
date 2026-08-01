from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from bot.database.models import Base, Book, Category, User


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_create_user(db_session):
    user = User(
        id=123456789,
        username="testuser",
        first_name="Test",
        last_name="User",
        language_code="en",
    )
    db_session.add(user)
    await db_session.commit()

    from sqlalchemy import select
    result = await db_session.execute(select(User).where(User.id == 123456789))
    fetched = result.scalar_one()
    assert fetched.username == "testuser"
    assert fetched.first_name == "Test"
    assert fetched.is_active is True
    assert fetched.is_banned is False


@pytest.mark.asyncio
async def test_create_category(db_session):
    category = Category(
        name="Technology",
        slug="technology",
        description="Tech books",
        icon="💻",
    )
    db_session.add(category)
    await db_session.commit()

    from sqlalchemy import select
    result = await db_session.execute(select(Category).where(Category.slug == "technology"))
    fetched = result.scalar_one()
    assert fetched.name == "Technology"


@pytest.mark.asyncio
async def test_create_book(db_session):
    category = Category(name="Fiction", slug="fiction", display_order=1)
    db_session.add(category)
    await db_session.commit()

    book = Book(
        title="Test Book",
        author="Test Author",
        description="A test book",
        category_id=category.id,
        file_size=1024000,
    )
    db_session.add(book)
    await db_session.commit()

    from sqlalchemy import select
    result = await db_session.execute(select(Book).where(Book.title == "Test Book"))
    fetched = result.scalar_one()
    assert fetched.author == "Test Author"
    assert fetched.id is not None
    assert len(fetched.id) == 36


@pytest.mark.asyncio
async def test_user_defaults(db_session):
    user = User(id=999)
    db_session.add(user)
    await db_session.commit()

    assert user.is_active is True
    assert user.is_banned is False
    assert user.total_downloads == 0


@pytest.mark.asyncio
async def test_book_string_id(db_session):
    book = Book(
        id="custom-id-123",
        title="Custom ID Book",
        author="Author",
    )
    db_session.add(book)
    await db_session.commit()

    from sqlalchemy import select
    result = await db_session.execute(select(Book).where(Book.id == "custom-id-123"))
    fetched = result.scalar_one()
    assert fetched.title == "Custom ID Book"
