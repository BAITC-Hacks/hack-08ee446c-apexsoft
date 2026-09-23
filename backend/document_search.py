"""Exact known catalogue articles in extracted document text, without AI guessing."""
import re


ARTICLE_TOKEN = re.compile(r'(?<![\w-])\w+(?:[-./]\w+)*(?![\w-])')


def document_matches(rows, attachments):
    """Return unique catalogue IDs in document order; no inferred product IDs.

    Input is Catalog.rows and the parsed attachment list. At most the existing
    request limit of four documents and 16,000 extracted characters each is read.
    Matching is case-insensitive; only catalogue articles' final underscore is
    optional. Duplicate catalogue articles retain all their IDs for user choice.
    """
    articles = {}
    for pid, row in rows.items():
        article = row.get('article')
        if not isinstance(article, str) or not re.fullmatch(r'\d{1,12}', str(pid)):
            continue
        key = article.strip().casefold().rstrip('_')
        if key:
            articles.setdefault(key, []).append(str(pid))
    result, seen = [], set()
    for attachment in attachments[:4]:
        if attachment.get('kind') != 'document':
            continue
        text = attachment.get('extracted_text')
        if not isinstance(text, str):
            continue
        for match in ARTICLE_TOKEN.finditer(text[:16000]):
            key = match.group().casefold().removesuffix('_')
            for pid in articles.get(key, ()):
                if pid not in seen:
                    seen.add(pid)
                    result.append(pid)
    return result
