from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional

from loguru import logger
from sqlalchemy import delete, desc, func, select, text, update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import joinedload

from bot.config.settings import settings
from bot.database.models import AdminLog, Base, Book, Category, Download, Favorite, User


class DatabaseService:
    def __init__(self) -> None:
        connect_args = {}
        engine_kwargs = {
            "echo": settings.environment == "development",
        }

        if settings.use_sqlite:
            connect_args["check_same_thread"] = False
        else:
            engine_kwargs["pool_size"] = settings.db_pool_min
            engine_kwargs["max_overflow"] = settings.db_pool_max - settings.db_pool_min
            engine_kwargs["pool_pre_ping"] = True

        self.engine = create_async_engine(
            settings.db_dsn,
            connect_args=connect_args,
            **engine_kwargs,
        )
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await self._migrate()
        logger.info("Database tables created successfully")

    async def _migrate(self) -> None:
        async with self.engine.begin() as conn:
            def _check_and_add(connection):
                result = connection.execute(text("PRAGMA table_info(books)"))
                cols = {row[1] for row in result}
                if "source" not in cols:
                    connection.execute(text("ALTER TABLE books ADD COLUMN source VARCHAR"))
                    logger.info("Migrated: added 'source' column to books table")
            await conn.run_sync(_check_and_add)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    # User operations

    async def get_or_create_user(
        self,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: Optional[str] = None,
    ) -> User:
        async with self.session() as session:
            result = await session.execute(select(User).where(User.id == telegram_id))
            user = result.scalar_one_or_none()

            if user:
                user.username = username
                user.first_name = first_name
                user.last_name = last_name
                user.language_code = language_code
                user.last_active_at = datetime.now(timezone.utc)
                return user

            user = User(
                id=telegram_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                language_code=language_code,
                country=None,
                last_active_at=datetime.now(timezone.utc),
            )
            session.add(user)
            logger.info(f"New user registered: {telegram_id}")
            return user

    async def get_user(self, telegram_id: int) -> Optional[User]:
        async with self.session() as session:
            result = await session.execute(select(User).where(User.id == telegram_id))
            return result.scalar_one_or_none()

    async def get_all_users(self, page: int = 1, per_page: int = 20) -> tuple[List[User], int]:
        async with self.session() as session:
            count_result = await session.execute(select(func.count(User.id)))
            total = count_result.scalar() or 0

            result = await session.execute(
                select(User)
                .order_by(desc(User.registered_at))
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            return list(result.scalars().all()), total

    async def get_user_count(self) -> int:
        async with self.session() as session:
            result = await session.execute(select(func.count(User.id)).where(User.is_active == True))
            return result.scalar() or 0

    async def ban_user(self, telegram_id: int) -> bool:
        async with self.session() as session:
            result = await session.execute(select(User).where(User.id == telegram_id))
            user = result.scalar_one_or_none()
            if user:
                user.is_banned = True
                user.is_active = False
                return True
            return False

    async def unban_user(self, telegram_id: int) -> bool:
        async with self.session() as session:
            result = await session.execute(select(User).where(User.id == telegram_id))
            user = result.scalar_one_or_none()
            if user:
                user.is_banned = False
                user.is_active = True
                return True
            return False

    async def is_user_banned(self, telegram_id: int) -> bool:
        async with self.session() as session:
            result = await session.execute(
                select(User.is_banned).where(User.id == telegram_id)
            )
            return result.scalar() or False

    async def get_banned_users(self) -> List[User]:
        async with self.session() as session:
            result = await session.execute(select(User).where(User.is_banned == True))
            return list(result.scalars().all())

    async def update_user_language(self, telegram_id: int, language: Optional[str]) -> User:
        async with self.session() as session:
            result = await session.execute(select(User).where(User.id == telegram_id))
            user = result.scalar_one_or_none()
            if user:
                user.preferred_language = language
                return user
            raise ValueError(f"User {telegram_id} not found")

    # Book operations

    async def create_book(self, book_data: dict) -> Book:
        async with self.session() as session:
            book = Book(**book_data)
            session.add(book)
            await session.flush()
            return book

    async def upsert_book_by_external_id(self, book_data: dict) -> Book:
        # Refreshes ALL book fields from a search result so download_url is never stale
        async with self.session() as session:
            ext_id = book_data.get("external_id")
            result = await session.execute(
                select(Book).where(Book.external_id == ext_id)
            )
            existing = result.scalar_one_or_none()
            if existing:
                for key, value in book_data.items():
                    if key not in ("id", "external_id"):
                        setattr(existing, key, value)
                await session.flush()
                return existing
            book = Book(**book_data)
            session.add(book)
            await session.flush()
            return book

    async def get_book(self, book_id: str) -> Optional[Book]:
        async with self.session() as session:
            result = await session.execute(
                select(Book)
                .options(joinedload(Book.category))
                .where(Book.id == book_id, Book.is_active == True)
            )
            return result.scalar_one_or_none()

    async def get_book_by_external_id(self, external_id: str) -> Optional[Book]:
        async with self.session() as session:
            result = await session.execute(
                select(Book).where(Book.external_id == external_id)
            )
            return result.scalar_one_or_none()

    async def search_books(
        self,
        query: str,
        field: str = "title",
        page: int = 1,
        per_page: int = 10,
    ) -> tuple[List[Book], int]:
        async with self.session() as session:
            base = select(Book).where(Book.is_active == True)
            search_pattern = f"%{query}%"

            if field == "title":
                base = base.where(Book.title.ilike(search_pattern))
            elif field == "author":
                base = base.where(Book.author.ilike(search_pattern))
            elif field == "isbn":
                base = base.where(Book.isbn.ilike(search_pattern))
            elif field == "all":
                base = base.where(
                    Book.title.ilike(search_pattern)
                    | Book.author.ilike(search_pattern)
                    | Book.isbn.ilike(search_pattern)
                    | Book.description.ilike(search_pattern)
                )
            else:
                base = base.where(Book.title.ilike(search_pattern))

            count_result = await session.execute(select(func.count()).select_from(base.subquery()))
            total = count_result.scalar() or 0

            result = await session.execute(
                base.options(joinedload(Book.category))
                .order_by(desc(Book.download_count))
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            return list(result.scalars().all()), total

    async def get_books_by_category(
        self, category_id: int, page: int = 1, per_page: int = 10
    ) -> tuple[List[Book], int]:
        async with self.session() as session:
            base = select(Book).where(Book.category_id == category_id, Book.is_active == True)

            count_result = await session.execute(select(func.count()).select_from(base.subquery()))
            total = count_result.scalar() or 0

            result = await session.execute(
                base.options(joinedload(Book.category))
                .order_by(desc(Book.download_count))
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            return list(result.scalars().all()), total

    async def get_popular_books(self, limit: int = 10) -> List[Book]:
        async with self.session() as session:
            result = await session.execute(
                select(Book)
                .options(joinedload(Book.category))
                .where(Book.is_active == True)
                .order_by(desc(Book.download_count))
                .limit(limit)
            )
            return list(result.scalars().all())

    async def get_recent_books(self, limit: int = 10) -> List[Book]:
        async with self.session() as session:
            result = await session.execute(
                select(Book)
                .options(joinedload(Book.category))
                .where(Book.is_active == True)
                .order_by(desc(Book.created_at))
                .limit(limit)
            )
            return list(result.scalars().all())

    async def increment_download_count(self, book_id: str) -> None:
        async with self.session() as session:
            await session.execute(
                update(Book)
                .where(Book.id == book_id)
                .values(download_count=Book.download_count + 1)
            )

    # Download operations

    async def record_download(
        self,
        user_id: int,
        book_id: str,
        method: Optional[str] = None,
        file_size: Optional[int] = None,
        successful: bool = True,
        error: Optional[str] = None,
    ) -> Download:
        async with self.session() as session:
            download = Download(
                user_id=user_id,
                book_id=book_id,
                download_method=method,
                file_size_bytes=file_size,
                is_successful=successful,
                error_message=error,
            )
            session.add(download)

            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(total_downloads=User.total_downloads + 1)
            )

            await session.flush()
            return download

    async def get_download_stats(self, days: int = 30) -> dict:
        async with self.session() as session:
            total = await session.execute(select(func.count(Download.id)))
            total_count = total.scalar() or 0

            from datetime import timedelta
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            recent = await session.execute(
                select(func.count(Download.id)).where(
                    Download.downloaded_at >= cutoff
                )
            )
            recent_count = recent.scalar() or 0

            top_books = await session.execute(
                select(Book.title, func.count(Download.id).label("dl_count"))
                .join(Download, Book.id == Download.book_id)
                .group_by(Book.id, Book.title)
                .order_by(desc("dl_count"))
                .limit(10)
            )

            return {
                "total_downloads": total_count,
                f"downloads_last_{days}_days": recent_count,
                "top_books": [{"title": r[0], "count": r[1]} for r in top_books.all()],
            }

    async def get_user_download_history(
        self, user_id: int, page: int = 1, per_page: int = 10
    ) -> tuple[List[Download], int]:
        async with self.session() as session:
            base = (
                select(Download)
                .options(joinedload(Download.book))
                .where(Download.user_id == user_id)
            )

            count_result = await session.execute(select(func.count()).select_from(base.subquery()))
            total = count_result.scalar() or 0

            result = await session.execute(
                base.order_by(desc(Download.downloaded_at))
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            return list(result.scalars().all()), total

    # Favorite operations

    async def add_favorite(self, user_id: int, book_id: str) -> bool:
        async with self.session() as session:
            existing = await session.execute(
                select(Favorite).where(
                    Favorite.user_id == user_id, Favorite.book_id == book_id
                )
            )
            if existing.scalar_one_or_none():
                return False

            favorite = Favorite(user_id=user_id, book_id=book_id)
            session.add(favorite)
            return True

    async def remove_favorite(self, user_id: int, book_id: str) -> bool:
        async with self.session() as session:
            result = await session.execute(
                delete(Favorite).where(
                    Favorite.user_id == user_id, Favorite.book_id == book_id
                )
            )
            return result.rowcount > 0

    async def get_user_favorites(
        self, user_id: int, page: int = 1, per_page: int = 10
    ) -> tuple[List[Favorite], int]:
        async with self.session() as session:
            base = (
                select(Favorite)
                .options(joinedload(Favorite.book).joinedload(Book.category))
                .where(Favorite.user_id == user_id)
            )

            count_result = await session.execute(select(func.count()).select_from(base.subquery()))
            total = count_result.scalar() or 0

            result = await session.execute(
                base.order_by(desc(Favorite.created_at))
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
            return list(result.scalars().all()), total

    async def is_favorite(self, user_id: int, book_id: str) -> bool:
        async with self.session() as session:
            result = await session.execute(
                select(Favorite).where(
                    Favorite.user_id == user_id, Favorite.book_id == book_id
                )
            )
            return result.scalar_one_or_none() is not None

    # Category operations

    async def get_all_categories(self) -> List[Category]:
        async with self.session() as session:
            result = await session.execute(
                select(Category).where(Category.is_active == True).order_by(Category.display_order)
            )
            return list(result.scalars().all())

    async def get_category(self, category_id: int) -> Optional[Category]:
        async with self.session() as session:
            result = await session.execute(
                select(Category).where(Category.id == category_id)
            )
            return result.scalar_one_or_none()

    async def seed_categories(self) -> None:
        async with self.session() as session:
            existing = await session.execute(select(func.count(Category.id)))
            count = existing.scalar()
            if count and count > 0:
                return

            categories = [
                Category(name="Fiction", slug="fiction", description="Fictional literature and novels", icon="📚", display_order=1),
                Category(name="Non-fiction", slug="non-fiction", description="Non-fictional works", icon="📖", display_order=2),
                Category(name="Academic", slug="academic", description="Academic and educational materials", icon="🎓", display_order=3),
                Category(name="Business", slug="business", description="Business and entrepreneurship", icon="💼", display_order=4),
                Category(name="Technology", slug="technology", description="Technology and computing", icon="💻", display_order=5),
                Category(name="Christian Books", slug="christian", description="Christian literature and theology", icon="✝️", display_order=6),
                Category(name="Self Development", slug="self-development", description="Personal growth and development", icon="🌱", display_order=7),
                Category(name="History", slug="history", description="Historical works", icon="🏛️", display_order=8),
                Category(name="Science", slug="science", description="Scientific literature", icon="🔬", display_order=9),
            ]
            session.add_all(categories)
            logger.info("Default categories seeded successfully")

    # Admin log operations

    async def log_admin_action(
        self,
        admin_id: int,
        action: str,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        async with self.session() as session:
            log = AdminLog(
                admin_id=admin_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                details=details,
            )
            session.add(log)

    async def get_admin_logs(self, limit: int = 50) -> List[AdminLog]:
        async with self.session() as session:
            result = await session.execute(
                select(AdminLog).order_by(desc(AdminLog.created_at)).limit(limit)
            )
            return list(result.scalars().all())

    async def get_dashboard_stats(self) -> dict:
        async with self.session() as session:
            users_total = await session.execute(select(func.count(User.id)))
            users_active = await session.execute(
                select(func.count(User.id)).where(User.is_active == True)
            )
            books_total = await session.execute(select(func.count(Book.id)))
            downloads_total = await session.execute(select(func.count(Download.id)))
            favorites_total = await session.execute(select(func.count(Favorite.id)))

            return {
                "total_users": users_total.scalar() or 0,
                "active_users": users_active.scalar() or 0,
                "total_books": books_total.scalar() or 0,
                "total_downloads": downloads_total.scalar() or 0,
                "total_favorites": favorites_total.scalar() or 0,
            }

    async def get_new_users_today(self) -> int:
        async with self.session() as session:
            from datetime import date
            today = date.today()
            result = await session.execute(
                select(func.count(User.id)).where(
                    func.date(User.registered_at) == today
                )
            )
            return result.scalar() or 0

    async def get_top_downloaded_books(self, limit: int = 5) -> List[Book]:
        return await self.get_popular_books(limit=limit)

    async def get_users_by_page(self, page: int, per_page: int = 10) -> tuple[List[User], int]:
        return await self.get_all_users(page=page, per_page=per_page)


db = DatabaseService()
