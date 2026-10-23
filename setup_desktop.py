"""Build the Mac app using pywebview's documented py2app packaging method.

    .venv/bin/python setup_desktop.py py2app
"""

from pathlib import Path

from setuptools import setup
from tls_security import require_build_environment

require_build_environment()

ROOT = Path(__file__).resolve().parent
APP_FILES = ["main.py", "app_ui.py", "app_presets.py", "run_data.py", "model_identity.py", "grid_view.py",
             "paper_prompts.py", "agent_view.py", "llm_api.py", "translations.py", "response_fields.py", "folder_picker.py",
             "experiment_task.py", "observations.py", "tls_security.py", "native_geometry.py",
             "requirements.txt", "requirements-desktop.txt", "LICENSE"]

setup(
    name="LLM SugarScape",
    version="0.1.0",
    app=[{"script": "desktop.py", "dest_base": "LLM SugarScape"}],
    data_files=[("", APP_FILES),
                ("native", ["native/libsugarscape_core.dylib", "native/build.json"]),
                ("rust-core", ["rust-core/Cargo.toml", "rust-core/Cargo.lock", "rust-core/rust-toolchain.toml"]),
                ("rust-core/src", ["rust-core/src/lib.rs"]),
                ("assets/emoji", [str(path.relative_to(ROOT)) for path in sorted((ROOT / "assets/emoji").iterdir()) if path.is_file()]),
                ("assets/branding", ["assets/branding/app-icon.png", "assets/branding/llm-sugar-scape-logo.png"])],
    options={"py2app": {
        "argv_emulation": False,
        "iconfile": "assets/branding/AppIcon.icns",
        "packages": ["streamlit", "aiohttp", "certifi", "numpy", "matplotlib", "pandas", "webview",
                     "uvicorn", "starlette", "websockets", "h11", "anyio"],
        # pandas._libs.testing imports cmath from compiled code, outside the
        # module graph py2app can discover from Python source.
        "includes": ["WebKit", "Foundation", "Security", "UniformTypeIdentifiers", "cmath"],
        "excludes": ["tkinter", "PySide6", "PyQt6", "pytest", "IPython", "pip", "ensurepip", "uv"],
        "plist": {
            "CFBundleIdentifier": "com.yukincom.llm-sugarscape",
            "CFBundleDisplayName": "LLM SugarScape",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "38",
            "CFBundleDevelopmentRegion": "ja",
            "CFBundleLocalizations": ["ja"],
            "LSMinimumSystemVersion": "26.2",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "Yuki (yukincom), MIT License",
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        },
    }},
)
