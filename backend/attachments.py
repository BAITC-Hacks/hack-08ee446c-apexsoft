import base64
import io
import math
import re
import threading
import zipfile
from pathlib import Path
from PIL import Image, ImageOps
from .errors import AppError

MAX_BYTES=8*1024*1024
MAX_TEXT=16000
MAX_PDF_IMAGES=4
MAX_PDF_SIDE=1600
MAX_PDF_IMAGE_BYTES=4*1024*1024
# PDFium is not thread-safe, including calls for different documents.
PDF_RENDER_LOCK=threading.Lock()
Image.MAX_IMAGE_PIXELS=20_000_000

def pdf_images(data,indices):
    import pypdfium2 as pdfium
    images=[]; rendered=[]; total_bytes=0
    with PDF_RENDER_LOCK:
        with pdfium.PdfDocument(data) as document:
            for index in indices[:MAX_PDF_IMAGES]:
                page=document[index]
                try:
                    width,height=page.get_size()
                    if not all(math.isfinite(v) and v>0 for v in (width,height)):
                        raise AppError('invalid_attachment','Некорректный размер страницы PDF.',422)
                    scale=min(2.0,MAX_PDF_SIDE/width,MAX_PDF_SIDE/height)
                    bitmap=page.render(scale=scale)
                    try:
                        img=bitmap.to_pil().convert('RGB')
                        try:
                            # A blank page is not an image to send to the model.
                            gray=img.convert('L')
                            try: blank=gray.getextrema()[0]>=250
                            finally: gray.close()
                            if blank: continue
                            out=io.BytesIO(); img.save(out,format='JPEG',quality=85)
                            encoded=out.getvalue(); total_bytes+=len(encoded)
                            if total_bytes>MAX_PDF_IMAGE_BYTES:
                                raise AppError('attachment_too_large','Изображения PDF слишком большие. Разделите документ на несколько файлов.',413)
                            images.append('data:image/jpeg;base64,'+base64.b64encode(encoded).decode('ascii'))
                            rendered.append(index+1)
                        finally: img.close()
                    finally: bitmap.close()
                finally: page.close()
    return images,rendered

def page_has_graphics(page):
    # Inspect dimensions before native image decoding, including nested forms.
    def inspect(resources,depth=0):
        if not resources: return False
        objects=resources.get_object().get('/XObject')
        if not objects: return False
        objects=objects.get_object()
        if depth>5 or len(objects)>100:
            raise AppError('attachment_too_large','Слишком сложная графика PDF. Разделите документ или загрузите фото страницы.',413)
        for reference in objects.values():
            obj=reference.get_object()
            if obj.get('/Subtype')=='/Image':
                width=float(obj.get('/Width',0));height=float(obj.get('/Height',0))
                if not all(math.isfinite(v) and v>0 for v in (width,height)) or width*height>20_000_000:
                    raise AppError('attachment_too_large','Изображение в PDF превышает 20 мегапикселей. Уменьшите разрешение скана.',413)
            elif obj.get('/Subtype')=='/Form': inspect(obj.get('/Resources'),depth+1)
        return True
    return inspect(page.get('/Resources'))

def parse_file(name,data):
    if not data or len(data)>MAX_BYTES: raise AppError('attachment_too_large','Размер файла должен быть от 1 байта до 8 МБ.',413)
    name=Path(name.replace('\\','/')).name
    suffix=Path(name).suffix.lower(); warnings=[]; image=None; images=[]
    if len(name)>160: name=name[:max(0,160-len(suffix))]+suffix[:160]
    try:
        if suffix in {'.docx','.xlsx'}:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if sum(i.file_size for i in archive.infolist())>32*1024*1024:
                    raise AppError('attachment_too_large','Слишком большой распакованный документ.',413)
        if suffix in {'.jpg','.jpeg','.png'}:
            with Image.open(io.BytesIO(data)) as img:
                if img.format not in {'JPEG','PNG'}: raise ValueError('image signature')
                img=ImageOps.exif_transpose(img).convert('RGB'); img.thumbnail((1600,1600))
                out=io.BytesIO(); img.save(out,format='JPEG',quality=85)
                image='data:image/jpeg;base64,'+base64.b64encode(out.getvalue()).decode('ascii')
            text='Изображение будет распознано моделью при отправке сообщения.'
        elif suffix=='.pdf':
            from pypdf import PdfReader
            if not data.startswith(b'%PDF'): raise ValueError('PDF signature')
            reader=PdfReader(io.BytesIO(data))
            if reader.is_encrypted: raise AppError('invalid_attachment','Снимите пароль с PDF перед загрузкой.',422)
            if len(reader.pages)>30: raise AppError('attachment_too_large','Максимум 30 страниц PDF.',413)
            texts=[page.extract_text() or '' for page in reader.pages]
            text='\n'.join(texts)
            graphics=[page_has_graphics(page) for page in reader.pages]
            candidates=[i for i in range(len(texts)) if not texts[i].strip() or graphics[i]]
            if candidates:
                images,rendered=pdf_images(data,candidates)
                if rendered:
                    warnings.append('Для распознавания подготовлены изображения страниц PDF: '+', '.join(map(str,rendered))+'. Текстовые данные документа также прочитаны; распознавание выполняется при отправке сообщения.')
                if len(candidates)>MAX_PDF_IMAGES:
                    warnings.append(f'Изображения обработаны только на первых {MAX_PDF_IMAGES} страницах, требующих распознавания. Разделите PDF, чтобы проверить остальные страницы.')
                    if not images and not text.strip():
                        raise AppError('invalid_attachment',f'На первых {MAX_PDF_IMAGES} страницах PDF нет читаемых данных. Прикрепите нужные страницы отдельным файлом.',422)
        elif suffix=='.docx':
            from docx import Document
            doc=Document(io.BytesIO(data))
            text='\n'.join([p.text for p in doc.paragraphs]+[' | '.join(c.text for c in row.cells) for t in doc.tables for row in t.rows])
        elif suffix=='.xlsx':
            import openpyxl
            book=openpyxl.load_workbook(io.BytesIO(data),read_only=True,data_only=True,keep_links=False)
            rows=[]; has_cells=False
            for sheet in book.worksheets[:5]:
                rows.append(sheet.title)
                for row in sheet.iter_rows(max_row=500,max_col=20,values_only=True):
                    rows.append(' | '.join(str(c) for c in row if c is not None))
                    has_cells=has_cells or any(c is not None and str(c).strip() for c in row)
            book.close(); text='\n'.join(rows) if has_cells else ''
            warnings.append('Для поиска прочитаны первые 5 листов, до 500 строк и 20 столбцов каждого.')
        elif suffix=='.xls':
            import xlrd
            book=xlrd.open_workbook(file_contents=data,on_demand=True)
            text='\n'.join(' | '.join(str(c) for c in sheet.row_values(r)[:20]) for sheet in book.sheets()[:5] for r in range(min(sheet.nrows,500)))
            book.release_resources(); warnings.append('Для поиска прочитаны первые 5 листов, до 500 строк и 20 столбцов каждого.')
        else:
            raise AppError('invalid_attachment','Поддерживаются JPEG, PNG, PDF, DOCX, XLSX и XLS. Старый Word DOC сохраните как DOCX.',422)
    except AppError: raise
    except Exception:
        raise AppError('invalid_attachment','Не удалось прочитать файл. Проверьте формат, целостность и отсутствие пароля.',422)
    if len(text)>MAX_TEXT: warnings.append('Текст ограничен первыми 16 000 символами; разделите длинную спецификацию.')
    text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',text[:MAX_TEXT])
    if not text.strip() and not image and not images:
        raise AppError('invalid_attachment','Документ пуст или не содержит читаемого текста и изображений. Прикрепите спецификацию или фото товара.',422)
    return {'name':name,'extracted_text':text,'kind':'image' if image else 'document','warnings':warnings,'image':image,'images':images}
