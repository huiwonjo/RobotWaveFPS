"""Package the existing Pygbag layout with the current code and game assets."""
from pathlib import Path
import tarfile
import zipfile

root = Path(__file__).resolve().parents[1]
game = root / 'game'
files = [game / 'main.py', game / 'favicon.png'] + sorted((game / 'assets').glob('*'))
with zipfile.ZipFile(root / 'game.apk', 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in files:
        if path.is_file():
            archive.write(path, 'assets/' + path.relative_to(game).as_posix())
with tarfile.open(root / 'game.tar.gz', 'w:gz', compresslevel=9) as archive:
    for path in files:
        if path.is_file():
            archive.add(path, 'assets/' + path.relative_to(game).as_posix())
with zipfile.ZipFile(root / 'game.apk') as archive:
    assert archive.testzip() is None
    assert archive.read('assets/main.py') == (game / 'main.py').read_bytes()
with tarfile.open(root / 'game.tar.gz') as archive:
    assert archive.extractfile('assets/main.py').read() == (game / 'main.py').read_bytes()
print('Web bundles updated:', len(files), 'files')
