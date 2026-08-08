# CSV encoding fixtures

The same logical CSV in the encodings our users' Excel installs actually
produce (Excel's default "CSV" save uses the SYSTEM codepage, not UTF-8 —
that's how the 2026-07-14 zh-CN churn happened). Consumed by
`../csv-decode.test.js`.

Do not hand-edit the non-UTF-8 files (editors re-save them as UTF-8 and
silently destroy the fixture). To regenerate the whole set:

```
cd extension/tests/fixtures && python - <<'EOF'
cases = {
    'utf8.csv':      ('utf-8',     'name,email\n张伟,zhang@example.com\nAyşe Yılmaz,ayse@example.com\n'),
    'utf8-bom.csv':  ('utf-8-sig', 'name,email\n张伟,zhang@example.com\n'),
    'ascii.csv':     ('ascii',     'name,email\nJohn Smith,john@example.com\n'),
    'gbk.csv':       ('gbk',       'name,email\n张伟,zhang@example.com\n李娜,lina@example.com\n'),
    # Mostly-ASCII list with only two Chinese names — 1.3% non-ASCII. Proves
    # the gb18030 gate keys on ADJACENT CJK, not on a ratio: a ratio rule
    # would reject this real Chinese file while accepting a Polish one.
    'gbk-diluted.csv': ('gbk',     'name,company,city,email\n张伟,Acme Corporation Limited,Beijing,zhang@example.com\nJohn Smith,Widgets Incorporated,London,john@example.com\nMaria Garcia,Global Trading Company,Madrid,maria@example.com\n李娜,Sunrise Technology Group,Shanghai,lina@example.com\nAnna Brown,Southern Logistics Inc,Bristol,anna@example.com\n'),
    'big5.csv':      ('big5',      'name,email\n張偉,zhang@example.com\n陳美玲,chen@example.com\n'),
    'shift_jis.csv': ('shift_jis', 'name,email\n田中太郎,tanaka@example.com\n'),
    'cp1251.csv':    ('cp1251',    'name,email\nИван Петров,ivan@example.com\n'),
    'cp1254.csv':    ('cp1254',    'name,email\nAyşe Yılmaz,ayse@example.com\nÇağrı Öztürk,cagri@example.com\n'),
    'cp1256.csv':    ('cp1256',    'name,email\nمحمد أحمد,mohammed@example.com\n'),
    # Mostly-ASCII Western file with a few stray high bytes (accents and a
    # Word smart quote) — the ONLY shape windows-1252 is allowed to claim.
    'cp1252.csv':    ('cp1252',    'name,email\nJosé Muñoz,jose@example.com\nZoë O’Brien,zoe@example.com\nAnne-Sophie Müller,anne@example.com\nJohn Smith,john@example.com\n'),
}
for fname, (enc, text) in cases.items():
    open(fname, 'wb').write(text.encode(enc))
import random
random.seed(42)
open('garbage.bin.csv', 'wb').write(bytes([0xFF, 0xFE, 0x00] + [random.randint(0x80, 0xFF) for _ in range(200)]))
EOF
```
