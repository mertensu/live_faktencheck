"""Tests for vector_store service."""

from unittest.mock import MagicMock, patch


class TestIndexExists:
    def test_index_exists_false_when_no_files(self, tmp_path, monkeypatch):
        """index_exists returns False when index files are absent."""
        import backend.services.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "INDEX_DIR", tmp_path)
        assert vs_mod.index_exists("no-such-episode") is False

    def test_index_exists_true_when_files_present(self, tmp_path, monkeypatch):
        """index_exists returns True when both index files are present."""
        import backend.services.vector_store as vs_mod
        monkeypatch.setattr(vs_mod, "INDEX_DIR", tmp_path)
        ep_dir = tmp_path / "my-episode"
        ep_dir.mkdir()
        (ep_dir / "index.faiss").touch()
        (ep_dir / "index.pkl").touch()
        assert vs_mod.index_exists("my-episode") is True


class TestBuildIndex:
    def test_build_index_saves_files(self, tmp_path):
        """build_index creates index.faiss and index.pkl in the episode dir."""
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.touch()

        mock_vs = MagicMock()
        mock_embeddings = MagicMock()

        with patch("backend.services.vector_store.INDEX_DIR", tmp_path), \
             patch("backend.services.vector_store._get_embeddings", return_value=mock_embeddings), \
             patch("backend.services.vector_store.FAISS") as mock_faiss_cls, \
             patch("fitz.open") as mock_fitz_open:

            mock_page = MagicMock()
            mock_page.get_text.return_value = "Test content"
            mock_doc = MagicMock()
            mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
            mock_doc.__enter__ = MagicMock(return_value=mock_doc)
            mock_doc.__exit__ = MagicMock(return_value=False)
            mock_fitz_open.return_value = mock_doc
            mock_faiss_cls.from_documents.return_value = mock_vs

            from backend.services.vector_store import build_index
            build_index("test-ep", [str(fake_pdf)])

            mock_vs.save_local.assert_called_once()
            save_path = mock_vs.save_local.call_args[0][0]
            assert "test-ep" in save_path


class TestCreateSearchTool:
    def test_create_search_tool_returns_none_when_no_index(self, tmp_path):
        """create_search_tool returns None when no index exists for episode."""
        with patch("backend.services.vector_store.INDEX_DIR", tmp_path):
            from backend.services.vector_store import create_search_tool
            tool = create_search_tool("missing-episode")
            assert tool is None

    def test_create_search_tool_returns_tool_when_index_exists(self, tmp_path):
        """create_search_tool returns a callable LangChain tool when index exists."""
        mock_vs = MagicMock()
        mock_retriever = MagicMock()
        mock_retriever.invoke.return_value = []
        mock_vs.as_retriever.return_value = mock_retriever

        with patch("backend.services.vector_store.INDEX_DIR", tmp_path), \
             patch("backend.services.vector_store.index_exists", return_value=True), \
             patch("backend.services.vector_store.load_vector_store", return_value=mock_vs):

            from backend.services.vector_store import create_search_tool
            search_tool = create_search_tool("test-ep")

            assert search_tool is not None
            assert search_tool.name == "search_document"
