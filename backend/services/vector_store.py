"""
FAISS vector store service for local PDF reference documents.

Provides per-episode FAISS indices that are built offline with index_pdfs.py
and loaded at fact-check time as a search_document tool for the LangChain agent.
"""

import logging
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

INDEX_DIR = Path("backend/data/vector_stores")


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
    text-embedding-004 model, and saves to backend/data/vector_stores/<episode_key>/.

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
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        for page_num, page in enumerate(doc):
            page_text = page.get_text()
            page_chunks = splitter.create_documents(
                [page_text],
                metadatas=[{"source": pdf_path, "page": page_num + 1}]
            )
            docs.extend(page_chunks)
        doc.close()
        logger.info(f"  → {page_count} pages")

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
    """
    vs = load_vector_store(episode_key)
    if vs is None:
        return None

    if pdf_paths:
        doc_names = ", ".join(Path(p).name for p in pdf_paths)
        description = (
            f"Durchsuche die offiziellen Referenzdokumente dieser Episode ({doc_names}). "
            f"Nutze dieses Tool ZUERST, bevor du eine allgemeine Websuche via Tavily startest, "
            f"wenn die Behauptung Bezug auf Parteiprogramme, Gesetzestexte oder andere "
            f"offizielle Dokumente nehmen könnte. "
            f"Die Suchergebnisse enthalten Seitenzahlen — zitiere diese in deiner Antwort."
        )
    else:
        description = (
            f"Durchsuche die offiziellen Referenzdokumente der Episode '{episode_key}' "
            f"(Wahlprogramme, Gesetzentwürfe, PDFs). "
            f"Nutze dieses Tool ZUERST, bevor du eine allgemeine Websuche via Tavily startest. "
            f"Die Suchergebnisse enthalten Seitenzahlen — zitiere diese in deiner Antwort."
        )

    retriever = vs.as_retriever(search_kwargs={"k": 5})

    @tool(name_or_callable="search_document", description=description)
    def search_document(query: str) -> str:
        """Search local reference documents and return results with page citations."""
        docs = retriever.invoke(query)
        if not docs:
            return "Keine relevanten Abschnitte in den Referenzdokumenten gefunden."
        return _format_docs(docs)

    return search_document
