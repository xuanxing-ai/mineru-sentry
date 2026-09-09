"""Repository for basic CRUD operations on ParseTaskEntity."""
from typing import List, Optional
from sqlalchemy.orm import Session
from core.entity.parse_task_entity import ParseTaskEntity


class ParseTaskRepo:
	"""
	Provides pure CRUD access for ParseTaskEntity without containing business logic.
	"""

	@staticmethod
	def add(session: Session, entity: ParseTaskEntity) -> ParseTaskEntity:
		"""
		Persists a new ParseTaskEntity instance into the database.
		:param session: Active SQLAlchemy database session.
		:param entity: ParseTaskEntity instance to insert.
		:return: Persisted entity.
		"""
		session.add(entity)
		session.commit()
		session.refresh(entity)
		return entity

	@staticmethod
	def update(session: Session, entity: ParseTaskEntity) -> ParseTaskEntity:
		"""
		Updates an existing ParseTaskEntity in the database.
		:param session: Active SQLAlchemy database session.
		:param entity: ParseTaskEntity instance to update.
		:return: Updated entity.
		"""
		session.merge(entity)
		session.commit()
		return entity

	@staticmethod
	def delete(session: Session, task_id: str) -> None:
		"""
		Deletes a ParseTaskEntity by primary key.
		:param session: Active SQLAlchemy database session.
		:param task_id: Primary key of the task to remove.
		"""
		entity = session.query(ParseTaskEntity).filter(ParseTaskEntity.id == task_id).first()
		if entity:
			session.delete(entity)
			session.commit()

	@staticmethod
	def get_by_id(session: Session, task_id: str) -> Optional[ParseTaskEntity]:
		"""
		Fetches a single ParseTaskEntity by primary key.
		:param session: Active SQLAlchemy database session.
		:param task_id: Primary key string.
		:return: ParseTaskEntity or None if not found.
		"""
		return session.query(ParseTaskEntity).filter(ParseTaskEntity.id == task_id).first()

	@staticmethod
	def list_by_file_hash(session: Session, file_hash: str) -> List[ParseTaskEntity]:
		"""
		Lists ParseTaskEntity records matching a specific SHA-256 hash ordered by creation time descending.
		:param session: Active SQLAlchemy database session.
		:param file_hash: SHA-256 hash string.
		:return: List of ParseTaskEntity records.
		"""
		return (
			session.query(ParseTaskEntity)
			.filter(ParseTaskEntity.file_hash == file_hash)
			.order_by(ParseTaskEntity.create_at.desc())
			.all()
		)

	@staticmethod
	def list_by_file_name(session: Session, file_name: str) -> List[ParseTaskEntity]:
		"""
		Lists ParseTaskEntity records matching a specific file name.
		:param session: Active SQLAlchemy database session.
		:param file_name: File name string.
		:return: List of ParseTaskEntity records.
		"""
		return (
			session.query(ParseTaskEntity)
			.filter(ParseTaskEntity.file_name == file_name)
			.order_by(ParseTaskEntity.create_at.desc())
			.all()
		)
