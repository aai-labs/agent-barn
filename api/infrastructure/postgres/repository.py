from typing import List, Literal, Optional, Type, TypeVar
from uuid import UUID

from sqlalchemy import create_engine, delete, func
from sqlmodel import Session, asc, col, desc, select

from api.infrastructure.postgres.models import BaseModel
from api.infrastructure.shared.models import PaginatedItems, Pagination
from api.core.config import Config

M = TypeVar("M", bound=BaseModel)


class PostgresRepositoryDelegate:
    def __init__(self, config: Config):
        self.engine = create_engine(
            url=str(config.db_connection_url),
            echo=False,
            pool_pre_ping=True,
            pool_size=50,
            max_overflow=10,
        )

    def _apply_filters_and_search(
        self,
        query,
        model: Type[M],
        search_term: str | None = None,
        search_field: str | None = None,
        **kwargs,
    ):
        filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
        query = query.filter_by(**filtered_kwargs)

        if search_term and search_field:
            filter_condition = getattr(model, search_field).ilike(f"%{search_term}%")
            query = query.filter(filter_condition)
        return query

    def _apply_ordering(
        self,
        query,
        model: Type[M],
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    ):
        if order_by:
            for column, direction in order_by:
                if direction.lower() == "asc":
                    query = query.order_by(asc(getattr(model, column)))
                elif direction.lower() == "desc":
                    query = query.order_by(desc(getattr(model, column)))
        return query

    def find_one(
        self,
        model: Type[M],
        search_term: str | None = None,
        search_field: str | None = None,
        **kwargs,
    ) -> M | None:
        with Session(self.engine) as session:
            query = select(model)
            query = self._apply_filters_and_search(
                model=model,
                query=query,
                search_term=search_term,
                search_field=search_field,
                **kwargs,
            )
            query = query.limit(1)
            result = session.exec(query)
            return result.first() or None

    def exists(self, model: Type[M], id: UUID) -> bool:
        with Session(self.engine) as session:
            id_column = getattr(model, "id")
            query = select(model).where(col(id_column) == id)
            result = session.exec(query)
            return result.first() is not None

    def find_by_id(self, model: Type[M], id: UUID) -> M | None:
        with Session(self.engine) as session:
            id_column = getattr(model, "id")
            query = select(model).where(col(id_column) == id)
            result = session.exec(query)
            return result.first()

    def find_all(
        self,
        model: Type[M],
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
        search_term: str | None = None,
        search_field: str | None = None,
        **kwargs,
    ) -> List[M]:
        with Session(self.engine) as session:
            query = select(model)
            query = self._apply_filters_and_search(
                model=model,
                query=query,
                search_term=search_term,
                search_field=search_field,
                **kwargs,
            )
            query = self._apply_ordering(query, model, order_by)
            result = session.exec(query)
            return list(result)

    def find_many(self, model: Type[M], ids: list[UUID]) -> List[M]:
        with Session(self.engine) as session:
            id_column = getattr(model, "id")
            query = select(model).where(col(id_column).in_(ids))
            result = session.exec(query)
            return list(result)

    def find_all_paginated(
        self,
        model: Type[M],
        pagination: Pagination | None = None,
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
        search_term: str | None = None,
        search_field: str | None = None,
        **kwargs,
    ) -> PaginatedItems[M]:
        with Session(self.engine) as session:
            query = select(model)
            query = self._apply_filters_and_search(
                model=model,
                query=query,
                search_term=search_term,
                search_field=search_field,
                **kwargs,
            )
            query = self._apply_ordering(query, model, order_by)
            if pagination:
                query = query.offset((pagination.page - 1) * pagination.size).limit(
                    pagination.size
                )

            total_query = select(func.count()).select_from(model)
            total_query = self._apply_filters_and_search(
                model=model,
                query=total_query,
                search_term=search_term,
                search_field=search_field,
                **kwargs,
            )

            total = session.exec(total_query).one()
            result = session.exec(query)
            items: List[M] = list(result)

            return PaginatedItems(
                page=pagination.page if pagination else 1,
                page_size=pagination.size if pagination else len(items),
                total=total,
                items=items,
            )

    def find_all_paginated_by_query(
        self,
        model: Type[M],
        query,
        pagination: Optional[Pagination] = None,
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    ) -> PaginatedItems[M]:
        with Session(self.engine) as session:
            count_query = query.with_only_columns(
                func.count(), maintain_column_froms=True
            ).order_by(None)
            total = session.scalar(count_query)

            query = self._apply_ordering(query, model, order_by)

            if pagination:
                query = query.offset((pagination.page - 1) * pagination.size).limit(
                    pagination.size
                )

            result = session.exec(query)
            items = list(result)
            return PaginatedItems(
                page=pagination.page if pagination else 1,
                page_size=pagination.size if pagination else len(items),
                total=total,
                items=items,
            )

    def find_all_by_query(
        self,
        model: Type[M],
        query,
        order_by: list[tuple[str, Literal["asc", "desc"]]] | None = None,
    ) -> list[M]:
        result = self.find_all_paginated_by_query(
            model=model,
            query=query,
            order_by=order_by,
        )
        return result.items

    def find_one_by_query(self, model: Type[M], query) -> M | None:
        with Session(self.engine) as session:
            result = session.exec(query)
            return result.one_or_none()

    def count(
        self,
        model: Type[M],
        search_term: str | None = None,
        search_field: str | None = None,
        **kwargs,
    ) -> int:
        with Session(self.engine) as session:
            total_query = select(func.count()).select_from(model)
            total_query = self._apply_filters_and_search(
                model=model,
                query=total_query,
                search_term=search_term,
                search_field=search_field,
                **kwargs,
            )
            total = session.exec(total_query).one()
            return total

    def count_by_query(self, query) -> int:
        with Session(self.engine) as session:
            total_query = query.with_only_columns(
                func.count(), maintain_column_froms=True
            ).order_by(None)
            total = session.scalar(total_query)
            return total

    def save(self, item: M):
        with Session(self.engine) as session:
            session.add(item)
            session.commit()
            session.refresh(item)

    def save_all(self, items: List[M]):
        with Session(self.engine) as session:
            session.add_all(items)
            session.commit()
            for item in items:
                session.refresh(item)

    def delete_one(self, model: Type[M], id) -> bool:
        with Session(self.engine) as session:
            id_column = getattr(model, "id")
            query = select(model).where(col(id_column) == id)
            result = session.exec(query)
            item = result.first()
            if not item:
                return False
            session.delete(item)
            session.commit()
            return True

    def delete(self, item) -> bool:
        with Session(self.engine) as session:
            session.delete(item)
            session.commit()
            return True

    def delete_many(self, items: List[M]):
        with Session(self.engine) as session:
            for item in items:
                session.delete(item)
            session.commit()
            return True

    def delete_all(self, model: Type[M], **kwargs) -> bool:
        with Session(self.engine) as session:
            filtered_kwargs = {k: v for k, v in kwargs.items() if v is not None}
            stmt = delete(model).filter_by(**filtered_kwargs)
            session.exec(stmt)
            session.commit()
            return True

    def close(self):
        self.engine.dispose()
