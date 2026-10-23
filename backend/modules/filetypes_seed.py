"""Built-in signature database (magic bytes). Seeded into the file_types table when it is empty.

scan_inside=True → this signature is also searched for INSIDE files (the "contains" relation).
Only for signatures of ≥ 4 bytes that aren't all zeros — shorter ones
would produce lots of false hits (e.g. 'MZ' appears in plain text).
"""

# (name, extension, magic HEX, offset, scan_inside)
SEED_TYPES = [
    ("PNG image", "png", "89504E470D0A1A0A", 0, True),
    ("JPEG image", "jpg", "FFD8FFE0", 0, True),  # JFIF
    ("JPEG image (EXIF)", "jpg", "FFD8FFE1", 0, True),
    ("JPEG image", "jpg", "FFD8FF", 0, False),  # other variants
    ("GIF image", "gif", "474946383961", 0, True),  # GIF89a
    ("GIF image", "gif", "474946383761", 0, True),  # GIF87a
    ("BMP image", "bmp", "424D", 0, False),
    ("TIFF image (LE)", "tif", "49492A00", 0, True),
    ("TIFF image (BE)", "tif", "4D4D002A", 0, True),
    ("Photoshop PSD", "psd", "38425053", 0, True),
    ("PDF document", "pdf", "255044462D", 0, True),  # %PDF-
    ("ZIP archive (also DOCX/JAR/APK)", "zip", "504B0304", 0, True),
    ("GZIP archive", "gz", "1F8B08", 0, False),
    ("7-Zip archive", "7z", "377ABCAF271C", 0, True),
    ("RAR archive", "rar", "526172211A07", 0, True),
    ("XZ archive", "xz", "FD377A585A00", 0, True),
    ("BZIP2 archive", "bz2", "425A68", 0, False),
    ("Zstandard archive", "zst", "28B52FFD", 0, True),
    ("Microsoft CAB", "cab", "4D534346", 0, True),
    ("TAR archive", "tar", "7573746172", 257, True),  # 'ustar' at offset 257
    ("ISO 9660 image", "iso", "4344303031", 32769, False),  # 'CD001'
    ("Windows Executable (PE/MZ)", "exe", "4D5A", 0, False),
    ("Linux ELF binary", "elf", "7F454C46", 0, True),
    ("Mach-O binary (64-bit)", "macho", "CFFAEDFE", 0, True),
    ("Java class", "class", "CAFEBABE", 0, True),
    ("Android DEX", "dex", "6465780A", 0, True),
    ("WebAssembly", "wasm", "0061736D", 0, True),
    ("SQLite database", "sqlite", "53514C69746520666F726D6174203300", 0, True),
    ("MP4/MOV video", "mp4", "66747970", 4, True),  # 'ftyp' at offset 4
    ("RIFF (WAV/AVI/WebP)", "riff", "52494646", 0, True),
    ("OGG media", "ogg", "4F676753", 0, True),
    ("FLAC audio", "flac", "664C6143", 0, True),
    ("MP3 audio (ID3)", "mp3", "494433", 0, False),
    ("UF2 firmware", "uf2", "5546320A", 0, True),  # 'UF2\n' (Raspberry Pi Pico etc.)
]
