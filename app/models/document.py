from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from app.database import Base


class Document(Base):
    """
    An uploaded file (annual report, earnings deck, filing, spreadsheet...).
    We store extracted text + a pre-computed summary so follow-up questions
    ("what were the biggest risks?") don't require re-parsing the file.
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    doc_type = Column(String, default="unknown")  # pdf, sheet, image
    extracted_text = Column(Text, default="")
    summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
