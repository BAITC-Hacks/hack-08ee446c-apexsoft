import base64
import io

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject,NumberObject

from backend.attachments import parse_file,MAX_PDF_IMAGES,MAX_PDF_SIDE
from backend.errors import AppError


def scan_pdf(pages=1):
    image=Image.new('RGB',(1000,400),'white')
    ImageDraw.Draw(image).text((40,50),'ARTICLE 150200334_ ECO-PRISMA 36W 6500K',fill='black',font_size=32)
    out=io.BytesIO();image.save(out,format='PDF',save_all=True,append_images=[image]*(pages-1));image.close()
    return out.getvalue()


def text_pdf():
    writer=PdfWriter();page=writer.add_blank_page(width=595,height=842)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 40 780 Td (Article 150200334_) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(content)
    out=io.BytesIO();writer.write(out);return out.getvalue()


def test_scanned_pdf_is_document_with_bounded_in_memory_images():
    result=parse_file('scan.pdf',scan_pdf())
    assert result['kind']=='document' and not result['extracted_text'].strip()
    assert len(result['images'])==1 and result['image'] is None
    image=Image.open(io.BytesIO(base64.b64decode(result['images'][0].split(',',1)[1])))
    assert image.format=='JPEG' and max(image.size)<=MAX_PDF_SIDE
    assert any('страниц PDF: 1' in w for w in result['warnings'])


def test_text_pdf_keeps_text_without_unnecessary_images():
    result=parse_file('text.pdf',text_pdf())
    assert '150200334_' in result['extracted_text'] and result['images']==[]


def test_mixed_pdf_preserves_text_and_scanned_page():
    writer=PdfWriter()
    for data in [text_pdf(),scan_pdf()]:
        writer.add_page(PdfReader(io.BytesIO(data)).pages[0])
    out=io.BytesIO();writer.write(out)
    result=parse_file('mixed.pdf',out.getvalue())
    assert '150200334_' in result['extracted_text'] and len(result['images'])==1
    assert any('страниц PDF: 2' in w for w in result['warnings'])


def test_many_scans_warn_about_unprocessed_pages():
    result=parse_file('five.pdf',scan_pdf(MAX_PDF_IMAGES+1))
    assert len(result['images'])==MAX_PDF_IMAGES
    assert any('остальные страницы' in w for w in result['warnings'])


def test_blank_pdf_and_empty_office_documents_have_clear_error():
    from docx import Document
    from openpyxl import Workbook
    writer=PdfWriter();writer.add_blank_page(width=595,height=842)
    pdf=io.BytesIO();writer.write(pdf)
    doc=io.BytesIO();Document().save(doc)
    sheet=io.BytesIO();Workbook().save(sheet)
    for name,data in [('empty.pdf',pdf.getvalue()),('empty.docx',doc.getvalue()),('empty.xlsx',sheet.getvalue())]:
        with pytest.raises(AppError) as error: parse_file(name,data)
        assert error.value.code=='invalid_attachment' and 'пуст' in error.value.message


def test_encrypted_and_more_than_thirty_pages_remain_rejected():
    writer=PdfWriter();writer.add_blank_page(width=595,height=842);writer.encrypt('test-only')
    out=io.BytesIO();writer.write(out)
    with pytest.raises(AppError) as error: parse_file('locked.pdf',out.getvalue())
    assert error.value.code=='invalid_attachment'
    writer=PdfWriter()
    for _ in range(31):writer.add_blank_page(width=595,height=842)
    out=io.BytesIO();writer.write(out)
    with pytest.raises(AppError) as error: parse_file('long.pdf',out.getvalue())
    assert error.value.code=='attachment_too_large'


def test_oversized_embedded_image_rejected_before_native_render():
    writer=PdfWriter();page=writer.add_blank_page(width=595,height=842)
    image=DecodedStreamObject();image.set_data(b'')
    image.update({NameObject('/Subtype'):NameObject('/Image'),NameObject('/Width'):NumberObject(100000),NameObject('/Height'):NumberObject(100000)})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/I'):writer._add_object(image)})})
    out=io.BytesIO();writer.write(out)
    with pytest.raises(AppError) as error:parse_file('large-image.pdf',out.getvalue())
    assert error.value.code=='attachment_too_large'


def test_concurrent_documents_render_without_sharing_native_state():
    from concurrent.futures import ThreadPoolExecutor
    data=scan_pdf()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:parse_file('scan.pdf',data),range(2)))
    assert all(len(result['images'])==1 for result in results)
