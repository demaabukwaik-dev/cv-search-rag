import sys
from dotenv import load_dotenv
from app.extract import extract_pdf  
from config import CVS_DIR  

load_dotenv()


def main():
    extractors = sys.argv[1:] or ["pymupdf", "llamaparse"]

    for pdf in sorted(CVS_DIR.glob("*.pdf")):
        for extractor in extractors:
            try:
                pages = extract_pdf(pdf, extractor)
            except Exception as error:
                print(f"\n[{extractor}] {pdf.name}: FAILED - {error}")
                continue
            print(f"\n[{extractor}] {pdf.name}: read {len(pages)} pages.")

if __name__ == "__main__":
    main()