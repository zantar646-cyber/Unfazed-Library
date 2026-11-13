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


@pytest.mark.asyncio
async def test_bulk_upsert_books():
    from bot.database.service import db

    books_data = [
        {"external_id": "ext-test-1", "title": "Book 1", "author": "Author A", "download_count": 5},
        {"external_id": "ext-test-2", "title": "Book 2", "author": "Author B", "download_count": 10},
    ]

    stored = await db.bulk_upsert_books_by_external_id(books_data)
    assert len(stored) == 2
    assert stored[0].title == "Book 1"
    assert stored[1].title == "Book 2"

    # Now update Book 1 and add Book 3 in the same batch
    updated_data = [
        {"external_id": "ext-test-1", "title": "Book 1 Updated", "author": "Author A", "download_count": 8},
        {"external_id": "ext-test-3", "title": "Book 3", "author": "Author C", "download_count": 1},
    ]
    stored_updated = await db.bulk_upsert_books_by_external_id(updated_data)
    assert len(stored_updated) == 2
    assert stored_updated[0].title == "Book 1 Updated"
    assert stored_updated[0].id == stored[0].id  # Keeps same primary key
    assert stored_updated[1].title == "Book 3"

    # Test get_books_by_ids
    fetched_books = await db.get_books_by_ids([stored_updated[0].id, stored_updated[1].id])
    assert len(fetched_books) == 2
    assert fetched_books[0].id == stored_updated[0].id
    assert fetched_books[1].id == stored_updated[1].id


def test_supabase_settings_detection(monkeypatch):
    from bot.config.settings import Settings

    # Case 1: DATABASE_URL provided (Supabase Pooler)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.myproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    )
    monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key-123")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "role-key-456")

    s = Settings()
    assert s.use_sqlite is False
    assert s.db_dsn == "postgresql+asyncpg://postgres.myproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    assert s.db_dsn_sync == "postgresql://postgres.myproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres"
    assert s.supabase_url == "https://myproject.supabase.co"
    assert s.supabase_anon_key == "anon-key-123"
    assert s.supabase_service_role_key == "role-key-456"

    # Case 2: SQLite fallback when DATABASE_URL is empty
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("POSTGRES_URL", raising=False)
    monkeypatch.setenv("USE_SQLITE", "true")
    s_sqlite = Settings()
    assert s_sqlite.use_sqlite is True
    assert "sqlite+aiosqlite" in s_sqlite.db_dsn


def test_database_service_postgresql_pooler_config(monkeypatch):
    from bot.config.settings import Settings
    from bot.database.service import DatabaseService
    import bot.database.service as svc

    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres.myproject:secret@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    )
    monkeypatch.setenv("VERCEL", "1")

    monkeypatch.setattr(svc, "settings", Settings())
    db_service = DatabaseService()

    # Verify asyncpg engine was created with NullPool for serverless and statement_cache_size=0
    assert db_service.engine.url.drivername == "postgresql+asyncpg"
    from sqlalchemy.pool import NullPool
    assert isinstance(db_service.engine.pool, NullPool)
