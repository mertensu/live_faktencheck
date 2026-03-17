"""
FAISS vector store service for local PDF reference documents.

Provides per-episode FAISS indices that are built offline with index_pdfs.py
and loaded at fact-check time as a search_document tool for the LangChain agent.
"""

import logging
from pathlib import Path

from langchain_core.tools.retriever import create_retriever_tool
from langchain_community.vectorstores import FAISS

logger = logging.getLogger(__name__)

INDEX_DIR = Path("backend/data/vector_stores")


def _get_embeddings():
    """Return Google Generative AI embeddings (uses existing GEMINI_API_KEY)."""
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(model="models/text-embedding-004")


def index_exists(episode_key: str) -> bool:
    """Return True if a FAISS index has been built for this episode."""
    path = INDEX_DIR / episode_key
    return (path / "index.faiss").exists() and (path / "index.pkl").exists()


def build_index(episode_key: str, pdf_paths: list[str]) -> None:
    """
    Build and save a FAISS vector store from local PDF files.

    Chunks each PDF into ~1000-character passages, embeds with Google's
    text-embedding-004 model, and saves to backend/data/vector_stores/<episode_key>/.

    Args:
        episode_key: Episode identifier (used as directory name)
        pdf_paths: List of local PDF file paths to index
    """
    import fitz  # pymupdf
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    docs = []

    for pdf_path in pdf_paths:
        if not Path(pdf_path).exists():
            logger.warning(f"PDF not found, skipping: {pdf_path}")
            continue
        logger.info(f"Reading PDF: {pdf_path}")
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        chunks = splitter.create_documents([text], metadatas=[{"source": pdf_path}])
        docs.extend(chunks)
        logger.info(f"  → {page_count} pages, {len(chunks)} chunks")

    if not docs:
        raise ValueError(f"No content extracted from PDFs for episode '{episode_key}'")

    embeddings = _get_embeddings()
    vectorstore = FAISS.from_documents(docs, embeddings)

    save_path = INDEX_DIR / episode_key
    save_path.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(save_path))
    logger.info(f"FAISS index saved: {save_path} ({len(docs)} chunks total)")


def load_vector_store(episode_key: str):
    """
    Load a previously built FAISS vector store for an episode.

    Returns:
        FAISS vector store, or None if no index exists.
    """
    if not index_exists(episode_key):
        return None
    embeddings = _get_embeddings()
    path = INDEX_DIR / episode_key
    return FAISS.load_local(str(path), embeddings, allow_dangerous_deserialization=True)


def create_search_tool(episode_key: str):
    """
    Create a LangChain retriever tool for the episode's local document index.

    Returns the tool if an index exists, None otherwise (so callers can check
    without crashing when no PDFs have been indexed).
    """
    vs = load_vector_store(episode_key)
    if vs is None:
        return None

    retriever = vs.as_retriever(search_kwargs={"k": 5})
    return create_retriever_tool(
        retriever,
        name="search_document",
        description=(
            "Search episode reference documents (Wahlprogramme, Gesetzentwürfe, PDFs) "
            "for content relevant to the claim being verified. "
            "Use this when Tavily search cannot find the needed information."
        ),
    )
