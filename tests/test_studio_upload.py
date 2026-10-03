"""Choosing a file in the Studio: a .docx is shown as script text that reads back as the same document."""
import io
import zipfile

import pytest

from kinodraw import ingest
from kinodraw.studio.server import docx_script

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _docx(paragraphs: list[tuple[str, str]]) -> bytes:
    body = ''.join(
        f'<w:p>{f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>" if style else ""}<w:r><w:t>{text}</w:t></w:r></w:p>'
        for style, text in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        z.writestr('word/document.xml', f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


@pytest.mark.parametrize('paragraphs', [
    [('Title', 'How Bees Talk'), ('', 'Bees dance to share news.'), ('Heading1', 'The waggle'),
     ('', 'A waggle points at food.'), ('Heading2', 'Distance'), ('', 'Longer waggles mean farther.'),
     ('Heading1', 'The round dance'), ('', 'A circle means food is near.')],
    [('', 'No headings at all, so the file name becomes the title.'), ('', 'A second paragraph.')],
])
def test_docx_text_reads_back_as_the_same_document(tmp_path, paragraphs):
    data = _docx(paragraphs)
    path = tmp_path / 'bee_dance.docx'
    path.write_bytes(data)
    text = docx_script(path.name, data)
    assert text.startswith('# ')
    assert ingest.read(text) == ingest.read(path)


def test_unreadable_files_say_why():
    with pytest.raises(ValueError, match='.md, .txt or .docx'):
        docx_script('YAC Reflection.pages', b'PK')
    with pytest.raises(ValueError, match='could not be read as a Word document'):
        docx_script('broken.docx', b'not a zip')
