from pathlib import Path

from vidgenie.config import Settings
from vidgenie.storage import Storage


def test_is_searchable_property(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    empty = st.save_media(b"x", "a.jpg", "image/jpeg")
    assert empty.description_status == "empty"
    assert empty.is_searchable is False

    empty.description = "deskripsi"
    empty.description_status = "filled"
    assert empty.is_searchable is True


def test_list_searchable_excludes_empty_description(tmp_path: Path) -> None:
    st = Storage(Settings(data_dir=tmp_path))
    filled = st.save_media(b"x", "b.jpg", "image/jpeg")
    filled.description = "deskripsi"
    filled.description_status = "filled"
    st.save_asset(filled)
    st.save_media(b"x", "c.jpg", "image/jpeg")

    result = st.list_searchable_assets()
    assert [a.filename for a in result] == ["b.jpg"]
