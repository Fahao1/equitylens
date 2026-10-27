"""Conservative, auditable headline/summary classifier; no unseen article claims."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import math
import re
from urllib.parse import urlsplit, urlunsplit

POSITIVE = {'beats estimates','earnings beat','record revenue','raises guidance','raised guidance',
            'revenue growth','profit growth','approval','approved','partnership','upgraded','buyback',
            'exceeds expectations','strong demand','dividend increase'}
NEGATIVE = {'misses estimates','earnings miss','cuts guidance','cut guidance','lowered guidance',
            'lawsuit','investigation','recall','downgraded','bankruptcy','revenue decline',
            'profit decline','weak demand','fraud','antitrust','data breach','layoffs'}
SIGNIFICANT = {'earnings','guidance','revenue','regulatory','lawsuit','bankruptcy','acquisition'}


def _timestamp(value):
    try:
        if isinstance(value,(int,float)):
            return datetime.fromtimestamp(value,timezone.utc)
        parsed = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError,TypeError,OverflowError):
        return None


def _url(value):
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme in ('http','https') and parsed.netloc:
            return urlunsplit((parsed.scheme,parsed.netloc,parsed.path.rstrip('/'),'',''))
    except ValueError:
        pass
    return None


def analyze_news(articles: list[dict], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    processed, seen_titles, seen_urls, weighted = [],set(),set(),[]
    bullish,bearish = [],[]
    for original in articles:
        title = str(original.get('title') or '').strip()
        if not title:
            continue
        normalized = re.sub(r'[^a-z0-9]','',title.lower())
        url = _url(original.get('url'))
        if normalized in seen_titles or (url and url in seen_urls):
            continue
        seen_titles.add(normalized)
        if url:
            seen_urls.add(url)
        timestamp = _timestamp(original.get('published_at'))
        # Future timestamps are not evidence available at the requested decision time.
        if timestamp and timestamp > now:
            continue
        summary = str(original.get('summary') or '').strip()
        text = (title+' '+summary).lower()
        positive,negative = sorted(word for word in POSITIVE if word in text),sorted(word for word in NEGATIVE if word in text)
        negated = bool(re.search(r'\b(?:not|no|denies|denied)\b.{0,30}(?:growth|approval|approved|partnership|fraud|lawsuit)',text))
        if negated or (positive and negative):
            sentiment = 'uncertain'
        elif positive:
            sentiment = 'positive'
        elif negative:
            sentiment = 'negative'
        else:
            sentiment = 'neutral'
        article = {**original,'id':str(original.get('id') or sha256((url or normalized).encode()).hexdigest()[:20]),
                   'title':title,'summary':summary or None,'url':url,
                   'publisher':original.get('publisher') or 'Unknown publisher',
                   'published_at':timestamp.isoformat() if timestamp else None,
                   'sentiment':sentiment,'sentiment_evidence':positive+negative,
                   'content_scope':'summary' if summary else 'headline',
                   'analysis_basis':'Keyword heuristic over the supplied headline'+(' and summary.' if summary else ' only.'),
                   'relevance':original.get('relevance','provider query match; company relevance unverified')}
        processed.append(article)
        if sentiment == 'positive':
            bullish.append({'text':title,'url':url,'article_id':article['id'],'basis':article['content_scope']})
        if sentiment == 'negative':
            bearish.append({'text':title,'url':url,'article_id':article['id'],'basis':article['content_scope']})
        age = (now-timestamp).total_seconds()/86400 if timestamp else None
        if age is not None and age <= 30 and url and sentiment != 'uncertain':
            significance = 1.3 if any(word in text for word in SIGNIFICANT) else 1.
            relevance = original.get('relevance')
            relevance_weight = max(0,min(1,float(relevance))) if isinstance(relevance,(int,float)) and math.isfinite(relevance) else .6
            weight = math.exp(-age/7)*significance*relevance_weight
            weighted.append(({'positive':7.5,'negative':2.5,'neutral':5}[sentiment],weight))
    processed.sort(key=lambda x:x['published_at'] or '',reverse=True)
    total = sum(w for _,w in weighted)
    score = sum(s*w for s,w in weighted)/total if total>0 else None
    confidence = min(.65,total/8) if total>0 else 0.
    limitations = ['Headline/summary keyword sentiment is a weak heuristic and may miss context, irony, financial magnitude or company relevance. Full articles were not read.',
                   'Exact normalized titles and canonical URLs are deduplicated; rewritten syndicated stories may remain.',
                   'Undated, future-dated, unlinked, uncertain or older-than-30-day stories do not contribute to the score. Neutral is a classification, not proof of no material news.',
                   'No upcoming company event is inferred from undated headlines. Consult the separately retrieved company earnings calendar.']
    if not processed:
        limitations.append('No eligible company news was returned by the source.')
    if score is None:
        limitations.append('Insufficient dated, source-linked news for a sentiment score.')
    return {'score':round(score,2) if score is not None else None,'confidence':round(confidence,3),
            'signals':[f'{len(processed)} distinct stories inspected at {"headline/summary"} scope; sentiment is not a return forecast.'] if processed else [],
            'limitations':limitations,'articles':processed,'bullish':bullish,'bearish':bearish,
            'upcoming_events':[],'method':'deterministic_headline_summary_keywords','llm_used':False}
