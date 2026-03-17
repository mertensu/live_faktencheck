"""
FAISS vector store service for local PDF reference documents.

Provides per-episode FAISS indices that are built offline with index_pdfs.py
and loaded at fact-check time as a search_document tool for the LangChain agent.
"""

import logging
from functools import lru_cache
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.tools import tool

from backend.utils import load_lang_config

logger = logging.getLogger(__name__)

# Anchored to this file's location so it works regardless of CWD
INDEX_DIR = Path(__file__).parent.parent / "data" / "vector_stores"


def _get_embeddings():
    """Return Google Generative AI embeddings (uses existing GEMINI_API_KEY)."""
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    return GoogleGenerativeAIEmbeddings(
        model="models/gemini-embedding-001",
        client_options={"api_endpoint": "generativelanguage.googleapis.com"},
    )


def index_exists(episode_key: str) -> bool:
    """Return True if a FAISS index has been built for this episode."""
    path = INDEX_DIR / episode_key
    return (path / "index.faiss").exists() and (path / "index.pkl").exists()


def build_index(episode_key: str, pdf_paths: list[str]) -> None:
    """
    Build and save a FAISS vector store from local PDF files.

    Chunks each PDF into ~1000-character passages, embeds with Google's
    gemini-embedding-001 model, and saves to backend/data/vector_stores/<episode_key>/.

    Args:
        episode_key: Episode identifier (used as directory name)
        pdf_paths: List of local PDF file paths to index
    """
    import fitz  # pymupdf
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # chunk_size ~5000 chars ≈ 1000-1250 tokens; overlap ~800 chars ≈ 200 tokens
    splitter = RecursiveCharacterTextSplitter(chunk_size=5000, chunk_overlap=800)
    docs = []

    for pdf_path in pdf_paths:
        if not Path(pdf_path).exists():
            logger.warning(f"PDF not found, skipping: {pdf_path}")
            continue
        logger.info(f"Reading PDF: {pdf_path}")
        with fitz.open(pdf_path) as doc:
            page_count = len(doc)
            for page_num, page in enumerate(doc):
                page_text = page.get_text()
                page_chunks = splitter.create_documents(
                    [page_text],
                    metadatas=[{"source": pdf_path, "page": page_num + 1}]
                )
                docs.extend(page_chunks)
        logger.info(f"  → {page_count} pages")

    if not docs:
        raise ValueError(f"No content extracted from PDFs for episode '{episode_key}'")

    embeddings = _get_embeddings()
    vectorstore = FAISS.from_documents(docs, embeddings)

    save_path = INDEX_DIR / episode_key
    save_path.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(save_path))
    logger.info(f"FAISS index saved: {save_path} ({len(docs)} chunks total)")


@lru_cache(maxsize=None)
def load_vector_store(episode_key: str):
    """
    Load a previously built FAISS vector store for an episode.

    Cached per episode_key so the index is only read from disk once per process.

    Returns:
        FAISS vector store, or None if no index exists.
    """
    if not index_exists(episode_key):
        return None
    embeddings = _get_embeddings()
    path = INDEX_DIR / episode_key
    # Validate path is inside INDEX_DIR before deserializing
    # allow_dangerous_deserialization is required by LangChain to load the pickled docstore
    assert path.resolve().is_relative_to(INDEX_DIR.resolve()), f"Unsafe index path: {path}"
    return FAISS.load_local(str(path), embeddings, allow_dangerous_deserialization=True)


def _format_docs(docs: list[Document]) -> str:
    """Format retrieved docs with filename and page number for LLM visibility."""
    parts = []
    for doc in docs:
        source = Path(doc.metadata.get("source", "Unbekannt")).name
        page = doc.metadata.get("page", "?")
        content = doc.page_content.replace("\n", " ")
        parts.append(f"[{source}, S. {page}]: {content}")
    return "\n\n---\n\n".join(parts)


def create_search_tool(episode_key: str, pdf_paths: list[str] | None = None):
    """
    Create a LangChain tool for the episode's local document index.

    Returns a custom tool that formats results with source and page number so
    the agent can cite them. Returns None if no index exists.

    Filenames are embedded in the tool description as (file1.pdf, file2.pdf)
    so that _inject_document_section can extract them for the agent prompt.
    """
    vs = load_vector_store(episode_key)
    if vs is None:
        return None

    lang_config = load_lang_config().get("tools", {})
    no_results_msg = lang_config.get("search_document_no_results", "No relevant sections found in the reference documents.")

    if pdf_paths:
        names = ", ".join(Path(p).name for p in pdf_paths)
        description = f"Search local reference documents ({names})."
    else:
        description = "Search local reference documents."

    retriever = vs.as_retriever(search_kwargs={"k": 5})

    @tool(name_or_callable="search_document", description=description)
    def search_document(query: str) -> str:
        """Search local reference documents and return results with page citations."""
        docs = retriever.invoke(query)
        if not docs:
            return no_results_msg
        return _format_docs(docs)

    return search_document
