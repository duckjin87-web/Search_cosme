"""DB 스키마. 제안서 6절 데이터 모델 + 조회 작업·업로드 테이블."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from searchcosme.db import Base

KST = timezone(timedelta(hours=9))


def now() -> datetime:
    return datetime.now(KST)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_key: Mapped[str] = mapped_column(String(300), unique=True, index=True)
    brand: Mapped[str] = mapped_column(String(120), default="")
    name: Mapped[str] = mapped_column(String(300))
    volume: Mapped[str] = mapped_column(String(60), default="")
    barcode: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    category: Mapped[str] = mapped_column(String(20), default="container")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    listings: Mapped[list["Listing"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class Listing(Base):
    """채널별 상품 페이지. 표기 원문을 그대로 보존한다."""
    __tablename__ = "listings"
    __table_args__ = (UniqueConstraint("product_id", "channel", "source_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(30))
    external_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_url: Mapped[str] = mapped_column(Text)
    title_raw: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    product: Mapped[Product] = relationship(back_populates="listings")


class Lookup(Base):
    __tablename__ = "lookups"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|error
    snapshot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LookupEvent(Base):
    """진행 상태. 워커가 쓰고 API(SSE)가 읽는다 → 프로세스가 달라도 동작."""
    __tablename__ = "lookup_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lookup_id: Mapped[str] = mapped_column(ForeignKey("lookups.id", ondelete="CASCADE"), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Snapshot(Base):
    __tablename__ = "snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    ruleset_version: Mapped[str] = mapped_column(String(40))
    channels: Mapped[list] = mapped_column(JSON, default=list)
    dedup_count: Mapped[int] = mapped_column(Integer, default=0)
    engine_info: Mapped[dict] = mapped_column(JSON, default=dict)


class Image(Base):
    __tablename__ = "images"
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    storage_key: Mapped[str] = mapped_column(Text)
    mime: Mapped[str] = mapped_column(String(40), default="image/jpeg")
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(Text)
    parent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Face(Base):
    __tablename__ = "faces"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    face: Mapped[str] = mapped_column(String(20))  # front..bottom | unclassified
    image_hash: Mapped[str] = mapped_column(ForeignKey("images.hash"))
    channel: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str] = mapped_column(Text)
    face_conf: Mapped[float] = mapped_column(Float)
    face_reason: Mapped[str] = mapped_column(Text, default="")
    ocr_conf: Mapped[float] = mapped_column(Float, default=0.0)
    ocr_lines: Mapped[list] = mapped_column(JSON, default=list)
    is_representative: Mapped[bool] = mapped_column(Boolean, default=False)


class Check(Base):
    __tablename__ = "checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(40))
    item_name: Mapped[str] = mapped_column(String(80))
    basis: Mapped[str] = mapped_column(String(80))
    faces: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20))
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="")
    values: Mapped[list["CheckValue"]] = relationship(cascade="all, delete-orphan")


class CheckValue(Base):
    __tablename__ = "check_values"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    check_id: Mapped[int] = mapped_column(ForeignKey("checks.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    channel: Mapped[str] = mapped_column(String(30))
    face: Mapped[str | None] = mapped_column(String(20), nullable=True)
    value_raw: Mapped[str] = mapped_column(Text)


class Upload(Base):
    """사내 업로드: 실물·도면 사진을 직접 올린 묶음."""
    __tablename__ = "uploads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    image_hash: Mapped[str] = mapped_column(ForeignKey("images.hash"))
    detail_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    face_hint: Mapped[str | None] = mapped_column(String(20), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CollectJob(Base):
    __tablename__ = "collect_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lookup_id: Mapped[str] = mapped_column(String(32), index=True)
    channel: Mapped[str] = mapped_column(String(30), index=True)
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
