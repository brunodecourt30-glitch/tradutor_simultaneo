# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — bundle .app do Tradutor Simultâneo para macOS

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# Tudo que precisa ser coletado dinamicamente
hidden = []
hidden += collect_submodules('faster_whisper')
hidden += collect_submodules('ctranslate2')
hidden += collect_submodules('deep_translator')
hidden += collect_submodules('edge_tts')
hidden += collect_submodules('huggingface_hub')
hidden += collect_submodules('tokenizers')
hidden += collect_submodules('onnxruntime')
hidden += collect_submodules('sounddevice')
hidden += collect_submodules('pydub')
hidden += collect_submodules('PIL')
hidden += ['bs4', 'soupsieve', 'aiohttp', 'certifi', 'charset_normalizer']

datas = []
datas += collect_data_files('faster_whisper')
datas += collect_data_files('ctranslate2')
datas += collect_data_files('huggingface_hub')
datas += collect_data_files('tokenizers')
datas += collect_data_files('onnxruntime')
datas += collect_data_files('certifi')
datas += [
    ('logo.png', '.'),
    ('microfone.png', '.'),
]

a = Analysis(
    ['tradutor_gui.py'],
    pathex=[],
    binaries=[
        ('/opt/homebrew/bin/ffmpeg', '.'),
        ('/opt/homebrew/bin/ffprobe', '.'),
    ],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Tradutor Simultâneo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='logo.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='Tradutor Simultâneo',
)

app = BUNDLE(
    coll,
    name='Tradutor Simultâneo.app',
    icon='logo.icns',
    bundle_identifier='com.tradutor.simultaneo',
    info_plist={
        'NSMicrophoneUsageDescription': 'Este app usa o microfone para gravar a fala que será traduzida.',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleVersion': '1.0.0',
        'CFBundleName': 'Tradutor Simultâneo',
        'CFBundleDisplayName': 'Tradutor Simultâneo',
    },
)
