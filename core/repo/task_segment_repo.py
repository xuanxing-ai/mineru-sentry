"""Repository for basic CRUD operations on TaskSegmentEntity."""
from typing import List, Optional
from sqlalchemy.orm import Session
from core.entity.task_segment_entity import TaskSegmentEntity


class TaskSegmentRepo:
	"""
	Provides pure CRUD access for TaskSegmentEntity records.
	"""

	@staticmethod
	def add(session: Session, entity: TaskSegmentEntity) -> TaskSegmentEntity:
		"""
		Persists a TaskSegmentEntity into the database.
		:param session: Active SQLAlchemy database session.
		:param entity: TaskSegmentEntity instance.
		:return: Persisted entity.
		"""
		session.add(entity)
		session.commit()
		session.refresh(entity)
		return entity

	@staticmethod
	def update(session: Session, entity: TaskSegmentEntity) -> TaskSegmentEntity:
		"""
		Updates an existing TaskSegmentEntity.
		:param session: Active SQLAlchemy database session.
		:param entity: TaskSegmentEntity instance to merge.
		:return: Updated entity.
		"""
		session.merge(entity)
		session.commit()
		return entity

	@staticmethod
	def delete(session: Session, segment_id: str) -> None:
		"""
		Deletes a TaskSegmentEntity by primary key.
		:param session: Active SQLAlchemy database session.
		:param segment_id: Primary key string.
		"""
		entity = session.query(TaskSegmentEntity).filter(TaskSegmentEntity.id == segment_id).first()
		if entity:
			session.delete(entity)
			session.commit()

	@staticmethod
	def get_by_id(session: Session, segment_id: str) -> Optional[TaskSegmentEntity]:
		"""
		Fetches a single TaskSegmentEntity by primary key.
		:param session: Active SQLAlchemy database session.
		:param segment_id: Primary key string.
		:return: TaskSegmentEntity or None if not found.
		"""
		return session.query(TaskSegmentEntity).filter(TaskSegmentEntity.id == segment_id).first()

	@staticmethod
	def list_by_task_id(session: Session, task_id: str) -> List[TaskSegmentEntity]:
		"""
		Lists all segments associated with a task ID ordered by segment_order ascending.
		:param session: Active SQLAlchemy database session.
		:param task_id: Primary key string of parent task.
		:return: List of TaskSegmentEntity instances.
		"""
		return (
			session.query(TaskSegmentEntity)
			.filter(TaskSegmentEntity.task_id == task_id)
			.order_by(TaskSegmentEntity.segment_order.asc())
			.all()
		)
