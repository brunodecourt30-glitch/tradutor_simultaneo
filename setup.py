from setuptools import setup

APP = ['tradutor_gui.py']
OPTIONS = {
    'argv_emulation': True,
    'packages': [
        'tkinter',
        'gtts',
        'googletrans',
        'speech_recognition',
        'sounddevice',
        'scipy',
        'requests',
        'httpx',
        'urllib3',
        'charset_normalizer'
    ],
    'includes': ['queue', 'os', 'threading', 'time', 'tempfile', 'subprocess'],
    'plist': {
        'CFBundleName': 'Tradutor Bilíngue com Voz',
        'CFBundleDisplayName': 'Tradutor Bilíngue com Voz',
        'CFBundleIdentifier': 'com.seu.nome.tradutor',
        'CFBundleVersion': '0.2.0',
        'CFBundleShortVersionString': '0.2.0',
    }
}

setup(
    app=APP,
    name='Tradutor Bilíngue com Voz',
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
