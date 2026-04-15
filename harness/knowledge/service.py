from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from utils.config_handler import agent_conf, chroma_conf, rag_conf
from utils.path_tool import get_abs_path


class KnowledgeService:
    """Owns vector loading and retrieval for local product knowledge."""

    def __init__(self) -> None:
        self.data_root = Path(get_abs_path(chroma_conf["data_path"]))
        self.md5_file = Path(get_abs_path(chroma_conf["md5_hex_store"]))
        self.vector_store = Chroma(
            collection_name=chroma_conf["collection_name"],
            embedding_function=DashScopeEmbeddings(model=rag_conf["embedding_model_name"]),
            persist_directory=get_abs_path(chroma_conf["persist_directory"]),
        )
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=int(chroma_conf["chunk_size"]),
            chunk_overlap=int(chroma_conf["chunk_overlap"]),
            separators=list(chroma_conf["separators"]),
            length_function=len,
        )
        self._synced = False

    def search(self, query: str) -> str:
        self.ensure_loaded()
        docs = self.vector_store.as_retriever(search_kwargs={"k": int(chroma_conf["k"])}).invoke(query)
        if not docs:
            return "未检索到相关知识。"

        lines: list[str] = []
        for index, doc in enumerate(docs, start=1):
            source = str(doc.metadata.get("source", "unknown"))
            snippet = doc.page_content.strip().replace("\n", " ")
            lines.append(f"[知识片段{index}] 来源: {source} 内容: {snippet[:400]}")
        return "\n".join(lines)

    def ensure_loaded(self) -> None:
        if self._synced:
            return
        if not self.md5_file.exists():
            self.md5_file.write_text("", encoding="utf-8")
        processed = {line.strip() for line in self.md5_file.read_text(encoding="utf-8").splitlines() if line.strip()}
        allowed_suffixes = tuple(chroma_conf["allow_knowledge_file_type"])
        for path in sorted(self.data_root.iterdir()):
            if not path.is_file() or not path.name.endswith(allowed_suffixes):
                continue
            digest = hashlib.md5(path.read_bytes()).hexdigest()
            if digest in processed:
                continue
            docs = self._load_documents(path)
            if not docs:
                continue
            chunks = self.splitter.split_documents(docs)
            if not chunks:
                continue
            self.vector_store.add_documents(chunks)
            with self.md5_file.open("a", encoding="utf-8") as f:
                f.write(digest + "\n")
        self._synced = True

    @staticmethod
    def _load_documents(path: Path) -> list[Document]:
        if path.suffix.lower() == ".pdf":
            return PyPDFLoader(str(path)).load()
        if path.suffix.lower() == ".txt":
            return TextLoader(str(path), encoding="utf-8").load()
        return []


class ReportDataService:
    """Reads local CSV report records without using legacy agent tools."""

    COLUMN_USER_ID = "用户ID"
    COLUMN_MONTH = "时间"

    def __init__(self) -> None:
        self.csv_path = Path(get_abs_path(agent_conf["external_data_path"]))

    def latest_month(self) -> str:
        months = sorted({row[self.COLUMN_MONTH] for row in self._rows() if row.get(self.COLUMN_MONTH)})
        return months[-1] if months else ""

    def available_user_ids(self) -> list[str]:
        return sorted({row[self.COLUMN_USER_ID] for row in self._rows() if row.get(self.COLUMN_USER_ID)})

    def fetch(self, user_id: str | None = None, month: str | None = None) -> dict:
        normalized_user_id = (user_id or "").strip()
        normalized_month = (month or "").strip() or self.latest_month()
        if not normalized_user_id:
            return {
                "error": "missing_user_id",
                "message": "缺少 user_id，无法生成个人报告。",
                "available_user_ids": self.available_user_ids(),
                "month": normalized_month,
            }

        for row in self._rows():
            if row.get(self.COLUMN_USER_ID) == normalized_user_id and row.get(self.COLUMN_MONTH) == normalized_month:
                return {
                    "user_id": normalized_user_id,
                    "month": normalized_month,
                    "feature": row.get("特征", ""),
                    "cleaning_efficiency": row.get("清洁效率", ""),
                    "consumables": row.get("耗材", ""),
                    "comparison": row.get("对比", ""),
                }
        return {
            "error": "report_not_found",
            "message": "未找到对应报告数据。",
            "user_id": normalized_user_id,
            "month": normalized_month,
            "available_user_ids": self.available_user_ids(),
        }

    def _rows(self) -> list[dict[str, str]]:
        with self.csv_path.open("r", encoding="utf-8") as f:
            return list(csv.DictReader(f))
