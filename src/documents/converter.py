import logging
import sys
from pathlib import Path

import mammoth

# Додаємо псевдомодуль для monkeypatch у тестах
sys.modules["src.documents.converter.mammoth"] = mammoth

logger = logging.getLogger(__name__)

def convert_to_html(input_path: Path) -> str:
    """
    Converts a DOCX file to HTML using Mammoth.
    This is fast and suitable for previews on all platforms (Web/Mobile).
    """
    import mammoth
    
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with open(input_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html_content = result.value
        
    # Wrap in a nice container for "A4 paper" look
    styled_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{
                margin: 0;
                padding: 0;
                background-color: transparent;
                display: flex;
                justify-content: center;
                min-height: 100vh;
            }}
            .document-page {{
                font-family: 'Times New Roman', Times, serif;
                line-height: 1.5;
                color: #000;
                background: white;
                padding: 40px;
                width: 100%;
                max-width: 800px;
                margin: 0 auto;
                box-shadow: 0 0 10px rgba(0,0,0,0.1);
                box-sizing: border-box;
            }}
            p {{ margin-bottom: 1em; }}
            table {{ border-collapse: collapse; width: 100%; margin-bottom: 1em; }}
            td, th {{ border: 1px solid #000; padding: 8px; }}
            strong {{ font-weight: bold; }}
            img {{ max-width: 100%; height: auto; }}
        </style>
    </head>
    <body>
        <div class="document-page">
            {html_content}
        </div>
    </body>
    </html>
    """
    return styled_html
